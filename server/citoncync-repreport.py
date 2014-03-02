#!/usr/local/bin/python

# Copyright 2014, Citon Computer Corporation
# Author: Paul Hirsch

# citoncync-repreport - Scan a given "basepath" directory for one or more
#                       CitonCync customer subdirectories then report to
#                       one or more email addresses on last sync, data usage
#                       and other fun facts.

## Imports
# General
import sys, os, stat, errno, traceback, time, re, datetime, platform

# Configuration
import ConfigParser     # XXX - Change this to "configparser" for Python 3
import optparse

# Reporting to console and via email with optional CSV output
import smtplib, email, logging, logging.handlers, csv

# Defaults
CONFFILE = "/etc/citoncync-repreport.conf"  # Default config file for repreport
RATEREGEX = 'Setting upload rate to (\d+)Kbps\s+\((\d+)\% of measured'
TIMEFORMAT = "%Y-%m-%d %H:%M:%S"

# Define our report column IDs - These will be posted at the top of CSV
# output in the order defined
COLNAMES = [
    'Customer',
    'Hostname',
    'Allocated Bytes',
    'Free Bytes',
    'Free %',
    'Host Used Bytes',
    'Last Start Time',
    'Last Completed Time',
    'Last Rate Limit',
    'Last Rate %',
    'Alert Flags'
]


# Handy lambda to pretty print file sizes - From Anonymous post to
# http://www.5dollarwhitebox.org/drupal/node/84
humansize = lambda s:[(s%1024**i and "%.1f"%(s/1024.0**i) or str(s/1024**i))+x.strip() for i,x in enumerate(' KMGTPEZY') if s<1024**(i+1) or i==8][0]


def listCustomers (basepath,dirmatch,ignorecusts):
    """
    List customer parent directories under basepath, ignoring anything that
    does not start with the dirmatch pattern or anything inside
    the ignorecusts array.  Returns array of customers.
    """

    customers = []
    pat = re.compile(r'^%s$' % dirmatch)

    for cust in os.listdir(basepath):
        try:
            # Try to stat the entity - One time only
            s = os.stat(os.path.join(basepath, cust))
        except os.error, err:
            continue
        
        # Only check directories
        if stat.S_ISDIR(s.st_mode):
            # Now make sure the pattern matches for the customer name 
            m = pat.search(cust)
            if m:
                if ignorecusts.count(cust) == 0:
                    customers.append(cust)
    
    return customers


def listCustomerHosts (basepath,customer,dirmatch):
    """
    List customer's hosts, ignoring anything that does not start with the
    dirmatch pattern. Returns array of host directory names.
    """

    hostdirs = []
    pat = re.compile(r'^%s$' % dirmatch)

    for hostn in os.listdir(os.path.join(basepath, customer)):
        try:
            # Try to stat the entity - One time only
            s = os.stat(os.path.join(basepath, customer, hostn))
        except os.error, err:
            continue
        
        # Only check directories
        if stat.S_ISDIR(s.st_mode):
            # Check the name
            m = pat.search(hostn)
            if m:
                hostdirs.append(hostn)

    return hostdirs


def getAllocSpace(folder):
    """ 
    Return folder/drive quota space (in bytes) - UNIX Only
    """
    return os.statvfs(folder).f_blocks * os.statvfs(folder).f_frsize


def getFreeSpace(folder):
    """ 
    Return folder/drive free space (in bytes) - UNIX Only
    """
    return os.statvfs(folder).f_bfree * os.statvfs(folder).f_frsize


def getUsedSpace(folder):
    """
    Return the number of bytes used by files under a specific folder.  Uses
    a hacked version of the os.walk code that tracks file sizes on the way
    to avoid multiple stat calls.
    """
    s = 0
    for root, dirs, files, sizes in walksize(folder):
        s += sizes

    return s


def walksize(top):
    """
    This is a direct copy of os.walk from Python2.6 with modifications
    to create a file size summary as it walks.  topdown, onerror,
    and followlinks are all negated.

    For each directory in the directory tree rooted at top (including top
    itself, but excluding '.' and '..'), yields a 4-tuple

        dirpath, dirnames, filenames, filesizes

    dirpath is a string, the path to the directory.  dirnames is a list of
    the names of the subdirectories in dirpath (excluding '.' and '..'),
    filenames is a list of the names of the non-directory files in dirpath,
    and filesizes is a total size in bytes of said files.

    Topdown processing is the only direction for walksize.
    Errors from the os.listdir() call are ignored.
    walksize does not follow symbolic links.

    # Example from os.walk modified to use "walksize"
    for root, dirs, files, sizes in walksize('python/Lib/email'):
        print root, "consumes",
        print sizes,
        print "bytes in", len(files), "non-directory files"
        if 'CVS' in dirs:
            dirs.remove('CVS')  # don't visit CVS directories
    """

    # We may not have read permission for top, in which case we can't
    # get a list of the files the directory contains.  os.path.walk
    # always suppressed the exception then, rather than blow up for a
    # minor reason when (say) a thousand readable directories are still
    # left to visit.  That logic is copied here.
    try:
        names = os.listdir(top)
    
    except os.error, err:
        return

    dirs, nondirs = [], []
    sizes = 0

    for name in names:
        try:
            # Try to stat the file - One time only
            s = os.stat(os.path.join(top, name))
        except os.error, err:
            continue
        
        if stat.S_ISDIR(s.st_mode):
            dirs.append(name)
        else:
            nondirs.append(name)
            # And bump the size!
            sizes += s.st_size

    yield top, dirs, nondirs, sizes
    
    for name in dirs:
        path = os.path.join(top, name)
        if not os.path.islink(path):
            for x in walksize(path):
                yield x


def getLastChange(folder, subfile):
    """
    Return the change time for a file under a specific base folder, or False if
    it does not exist
    """

    cfile = os.path.join(folder, subfile)

    if not os.path.isfile(cfile):
        return False

    return os.path.getmtime(cfile)


def getLastRate(folder, lastlogfile):
    """
    Search lastlogfile under folder for a line reporting the bandwidth
    rate and percentage used for a citoncync run. Returns tuple with bandwidth
    as element 0 and percentage limit as element 1. 0,0 is returned on error
    to allow fails to be included in averages, etc without breaking your calcs.
    """
    
    cfile = os.path.join(folder, lastlogfile)

    if not os.path.isfile(cfile):
        return ('0', '0')

    try:
        lfh = open(cfile, 'r')
    except OSError:
        # Skip file
        return ('0', '0')
    
    # Look for our rate line
    m = re.findall(RATEREGEX, lfh.read())

    if len(m):
        return m[0]
    else:
        return ('0', '0')


def timeString(rawdate):
    """
    Take in a UNIX time and retrun a friendly time string, or "never" if false
    """

    try:
        if rawdate:
            stime = time.strftime(TIMEFORMAT, time.localtime(rawdate))
        else:
            stime = "never"
    except:
        return "never"

    return stime


class Configure(ConfigParser.ConfigParser):
    """
    Read and maintain configuration settings - Customized for this program.
    All supported options must be filtered/copied in by this class
    """

    def __init__(self):
        """
        Read in configuration from command line and config file(s).  Stores
        a cleaned dictionary called "settings" that should be usable without
        further processing
        """
        ConfigParser.ConfigParser.__init__(self)

        settings = {}

        # Parse arguments - XXX - Move this to argparse soon
        #  Great example of merged ConfigParser/argparse:
        #  http://blog.vwelch.com/2011/04/combining-configparser-and-argparse.html
        progname = os.path.basename(__file__)
        parser = optparse.OptionParser(usage="%s [-c FILE] [-fmwvd]" % progname)
        parser.add_option("-c", "--config", dest="conffile", help="use configuration from FILE", metavar="FILE")
        parser.add_option("-f", "--fast", dest="faston", action="store_true", default=False, help="skip per-host usage and other slow stats")
        parser.add_option("-m", "--mail", dest="emailon", action="store_true", default=False, help="send email report")
        parser.add_option("-w", "--warn", dest="warnonly", action="store_true", default=False, help="only report when there are hosts with low space or past due replication warnings")
        parser.add_option("-v", "--csv", dest="csvon", action="store_true", default=False, help="output CSV report")
        parser.add_option("-d", "--debug", dest="debugon", action="store_true", default=False, help="enable debug mode")

        # Parse!
        (options, args) = parser.parse_args()
        
        if options.conffile is None:
            # No config passed, so try the default
            conffile = CONFFILE
        else:
            conffile = options.conffile

        if not os.path.isfile(conffile):
            # This is just a quick check that the config file exists
            parser.error("Configuration file %s not found" % conffile)

        try:
            # Read in configuration file
            self.read(conffile)
        except ValueError:
            raise GeneralError("Bad value in config file - Check your %(variable)s replacements!")

        if not self.has_section('conf'):
            raise GeneralError("You MUST have a [conf] section! None found in %s\n" % conffile)

        # The current config file setup only cares about the [conf] settings
        # at this time.  It will be stored in the settings hash

        # Check for required settings under the [conf] section
        req = ['instancename', 'basepath', 'ignorecusts', 'dirmatch', 'bwtestfile', 'lastlogfile', 'alertfreepercent', 'alertfreegb', 'alertstale'] 
        errs = ""
        for item in req:
            if not self.has_option('conf', item):
                errs += "\n* You must set '%s' in your configuration file" % item
            else:
                settings[item] = self.get('conf', item)

        if errs:
            # Spit out all missing parameters at once
            raise GeneralError(errs)

        # Add the hostname to the instancename
        settings['instancename'] = "%s (%s)" % (settings['instancename'], platform.node())

        # Pull in remaining CLI args
        settings['emailon'] = options.emailon
        settings['faston'] = options.faston
        settings['warnonly'] = options.warnonly
        settings['debugon'] = options.debugon
        settings['csvon'] = options.csvon

        # Set other items based on the fast flag
        if settings['faston']:
            # The per-host usage calc requires checking every file in the host
            # folders.  This is IO intensive, especially for a large file count.
            # Note that the per-customer stats are still accurate as long
            # as each is under thier own logical FS or ZFS folder
            settings['skiphostused'] = True
        else:
            settings['skiphostused'] = False

        # Set our loglevel based on the warnonly and debug flags
        if settings['debugon']:
            settings['loglevel'] = 'DEBUG'
        elif settings['warnonly']:
            settings['loglevel'] = 'WARNING'
        else:
            settings['loglevel'] = 'INFO'

        # If SMTP reporting is enabled, check for those required values
        if settings['emailon']:
            req = ['smtpserver', 'emailto', 'emailfrom'] 
            errs = ""
            for item in req:
                if not self.has_option('conf', item):
                    errs += "\n* For SMTP reports, you must set '%s' in your configuration file" % item
                else:
                    if item == 'emailto':
                        settings[item] = self.get('conf', item).split(',')
                    else:
                        settings[item] = self.get('conf', item)
                        
            if errs:
                # Spit out all missing parameters at once
                raise GeneralError(errs)

            
        # Save screened settings back to config 
        self.settings = settings

    def get_settings(self):
        """
        Return the stored settings dictionary
        """
        return self.settings

    def boolcheck(self, value):
        """
        A more user-friendly True/False checker - Returns True on affirmative
        including:
         1
         yes
         YES
         tRuE
         Word
         Si
        All else is considered False
        """

        if re.match('^(1|yes|true|on|yo|si|word)$', value, re.IGNORECASE):
            return True
        else:
            return False


class EmailReportHandler(logging.Handler):
    """
    Buffer and generate email reports
    """

    def __init__(self, smtpserver, fromaddr, toaddrs, subjectprefix):
        """
        Setup email reporter:

         smtpserver - Hostname or IP of SMTP relay
         fromaddr - String with email address of sender
         toaddrs - Array of email addresses to send to
         subjectprefix - Common prefix to prepend to all subject lines
        """

        logging.Handler.__init__(self)

        self.smtpserver = smtpserver
        self.fromaddr = fromaddr
        self.toaddrs = toaddrs
        self.subjectprefix = subjectprefix

        # Start with an empty buffer and a NOTSET (0) level high water mark
        self.buf = ""
        self.maxlevel = 0
        self.starttime = time.strftime("%Y-%m-%d %H:%M:%S")

    def emit(self, record):
        """
        Add line to buffer (This is different than most logging handlers,
        which would ship the message immediately on an emit)
        """

        # Save the text
        self.buf += self.format(record) + "\r\n"

        # Update our high water mark for collected messages
        if record.levelno > self.maxlevel: self.maxlevel = record.levelno

    def send(self, subject, body):
        """
        Send email report with a given subject line and body
        """
        
        # Add runtime info and combine the body provided as an argument
        # with the collected logs
        body += "\r\nStart Time: %s" % self.starttime
        body += "\r\nEnd Time  : %s" % time.strftime("%Y-%m-%d %H:%M:%S") 
        body += "\r\n\r\n" + self.buf

        msg = email.Message.Message()

        # Check maximum level and add a special note in the subject for anything
        # above INFO
        if self.maxlevel > 20:
            notice = "(" + logging.getLevelName(self.maxlevel) + " ALERT) "
        else:
            notice = ""

        # Build our message header
        msg.add_header('From', self.fromaddr)
        for t in self.toaddrs:
            msg.add_header('To', t)
        msg.add_header('Subject', "%s %s %s" % (self.subjectprefix, notice, subject))
        msg.set_payload(body)

        # Fire!
        try:
            server = smtplib.SMTP(self.smtpserver)
            
            # server.set_debuglevel(1)

            server.sendmail(msg['From'], msg.get_all('To'), msg.as_string())
            server.quit()
        except Exception, err:
            raise GeneralError("Email report failure: %s" % err)




class Error(Exception):
    """
    Base class for custom exceptions
    """
    pass


class GeneralError(Error):
    """
    Well handled exceptions - These represent normal operation errors and not
    coding or critical system problems
    """

    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg


def main ():

    # Report time
    proctime = time.time()

    # Get configuration with our special Config class
    conf = Configure()
            
    # Pull settings hash for quick access
    sets = conf.get_settings()


    # Setup base logger and formatting
    logger = logging.getLogger('CitonCync-RepReport')
    logger.setLevel(sets['loglevel'])
    
    # Just the message
    format = logging.Formatter('%(message)s')

    # Simple console logger
    clog = logging.StreamHandler()
    clog.setFormatter(format)
    logger.addHandler(clog)
    
    # Custom EmailReport handler - Designed to collect all messages and send
    # one blast at the end
    if sets['emailon']:
        elog = EmailReportHandler(sets['smtpserver'], sets['emailfrom'], sets['emailto'], "%s" % sets['instancename'])
        elog.setFormatter(format)
        logger.addHandler(elog)

    
    r = {}
    warnings = 0
    hosts = 0

    # Wrap in try to catch exceptions using our custom classes

    try:
        # Cycle through customer/hostname directories
        logger.debug("Starting processing under %s" % sets['basepath'])
        for c in listCustomers(sets['basepath'], sets['dirmatch'], sets['ignorecusts']):
            r[c] = {}
            logger.debug("Processing customer %s" % c)
        
            for h in listCustomerHosts(sets['basepath'], c, sets['dirmatch']):
                r[c][h] = {}
                hosts += 1
                hdir = os.path.join(sets['basepath'], c, h)
                logger.debug("Checking stats for %s/%s" % (c, h))

                # Gather stats
                r[c][h]['alloc'] = getAllocSpace(hdir)
                r[c][h]['free'] = getFreeSpace(hdir)
                r[c][h]['freepercent'] = int((100 * r[c][h]['free']) / r[c][h]['alloc'])
                if sets['skiphostused']:
                    r[c][h]['hostused'] = 'n/a'
                else:
                    r[c][h]['hostused'] = getUsedSpace(hdir)

                r[c][h]['laststart'] = getLastChange(hdir, sets['bwtestfile'])
                r[c][h]['lastcomplete'] = getLastChange(hdir, sets['lastlogfile'])
                (r[c][h]['lastratelimit'], r[c][h]['lastratepercent']) = getLastRate(hdir, sets['lastlogfile'])
                
                # Clear warn flag
                r[c][h]['warnflag'] = False
                alertlist = []
                logger.debug("Checking alerts")
                
                # Test for percentage of disk space free
                if r[c][h]['freepercent'] <= int(sets['alertfreepercent']):
                    r[c][h]['alertfreepercent'] = True
                    r[c][h]['warnflag'] = True
                    alertlist.append("ALERT-FREE%")
                    logger.debug("Free Percent Failure for %s/%s" % (c, h))
                else:
                    r[c][h]['alertfreepercent'] = False

                # Test for absolute disk space free in GB
                if r[c][h]['free'] <= (int(sets['alertfreegb']) * 1024 * 1024 * 1024):
                    r[c][h]['alertfreegb'] = True
                    r[c][h]['warnflag'] = True
                    alertlist.append("ALERT-FREE-GB")
                    logger.debug("Free GB Failure for %s/%s" % (c, h))
                else:
                    r[c][h]['alertfreegb'] = False
            
                # Test for staleness of last replication completion
                if (r[c][h]['lastcomplete'] and (r[c][h]['lastcomplete'] > (proctime - float(sets['alertstale'])))):
                    r[c][h]['alertstale']  = False
                else:
                    r[c][h]['alertstale']  = True
                    r[c][h]['warnflag'] = True
                    alertlist.append("ALERT-LATE")
                    logger.debug("Staleness Failure for %s/%s" % (c, h))

                r[c][h]['alertlist'] = alertlist

                
        # Force out a header if CSV is enabled
        if sets['csvon']:
            logger.info(','.join(COLNAMES))

        # Now cycle through customers and hosts in order and build our report
        for c in sorted(r.iterkeys()):
            for h in sorted(r[c].iterkeys()):
                # Build our output to be plain text or CSV
                logger.debug("Generating Report Line for %s/%s" % (c, h))
                if len(r[c][h]['alertlist']):
                    alerttext = " ".join(r[c][h]['alertlist'])
                else:
                    alerttext = "OK"
                    
                if sets['csvon']:
                    oline = '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s' % (
                        c,
                        h,
                        r[c][h]['alloc'],
                        r[c][h]['free'],
                        r[c][h]['freepercent'],
                        r[c][h]['hostused'],
                        timeString(r[c][h]['laststart']),
                        timeString(r[c][h]['lastcomplete']),
                        r[c][h]['lastratelimit'],
                        r[c][h]['lastratepercent'],
                        alerttext
                        )
                else:
                    r[c][h]['alloc'] = humansize(r[c][h]['alloc'])
                    r[c][h]['free'] = humansize(r[c][h]['free'])
                    if not sets['skiphostused']:
                        r[c][h]['hostused'] =  humansize(r[c][h]['hostused'])
                        
                    oline = "===============\n%s/%s\n\tAllocated/Free (Free%%): %s / %s (%s%%)\n\tHost Used: %s\n\tLast Replication Start Time: %s\n\tLast Completed Replication Time: %s\n\tLast Rate Limit (Rate%%): %sKbps (%s%%)\n\tSTATUS: %s\n==============\n\n\n" % (
                        c,
                        h,
                        r[c][h]['alloc'],
                        r[c][h]['free'],
                        r[c][h]['freepercent'],
                        r[c][h]['hostused'],
                        timeString(r[c][h]['laststart']),
                            timeString(r[c][h]['lastcomplete']),
                        r[c][h]['lastratelimit'],
                        r[c][h]['lastratepercent'],
                        alerttext
                        )
                
                # Push the host results using info for normal lines or
                # warning for alert lines
                if r[c][h]['warnflag']:
                    logger.warning(oline)
                    warnings += 1
                else:
                    logger.info(oline)
                    
                    
        # Send email if enabled and warranted
        if sets['emailon']:
            if warnings:
                elog.send(": %s hosts checked [%s WARNING(S)] (%s)" % (str(hosts), str(warnings), time.strftime(TIMEFORMAT)), "%s Report - %s of %s hosts with warnings" % (sets['instancename'], str(warnings), str(hosts)))
            else:
                if not sets['warnonly']:
                    elog.send(": %s hosts checked [ALL OK] (%s)" % (str(hosts), time.strftime(TIMEFORMAT)), "%s Report - All %s hosts ok" % (sets['instancename'], str(hosts)))
    
    
    except GeneralError as detail:
        logger.warning("GeneralError: %s" % detail)
        sys.exit(1)
    except:
        logger.error("Unexpected errors were encountered - Please review and forward to support: %s" % "; ".join(traceback.format_exc().splitlines()))
        
    exit(0)


if __name__ == '__main__':
    main()
