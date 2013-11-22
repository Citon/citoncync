CitonCync - Simple replication to cloud storage
-----------------------------------------------------------------------------

One of Citon's hosted services is a RSync over SSH target for archive storage.
CitonCync was created to simplify setting up the client side, particularly
on commodity NAS devices.

Citon's RSync service requires:

 * SSH with public key authentication to provide an authenticated and secure
   path for data in flight
 * Scripted push from client device to a hosted target server
 * Per-client accounts, each chrooted to prevent cross client tampering
 
Target hosts run FreeNAS and the "server" directory contains scripts to
ease creation and management of chrooted accounts.

Source hosts can be any system supporting SSH.  RSync is generally used over
SSH to provide efficient replication.

The following client scripts are provided:

 * citoncync-generic - Client script template for generic UNIX/Linux
 * citoncync-qnap - Client script template with QNAP targeted defaults
 * citoncync-phdvba - Client script template with PHD Virtual VBA defaults

For installation, copy either "citoncync-generic" or "citoncync-qnap" to
a new file named "citoncync" and modify the new file to match your
environment.

The citoncync-lib shell file contains the logic common to all clients.

CLIENT INSTALLATION
-------------------

 * Copy the latest citoncync-x.y.tgz to your client machine
 * Unpack the archive in a suitable location.  On most NAS devices this should
   be under the base of their disk storage area (/share/MD0_DATA for QNAP).
   Many NAS systems do not keep files kept outside of this area on reboot.

   Example: (Assumes you saved the .tgz to /share/MD0_DATA)

   	    cd /share/MD0_DATA
	    tar xvzf citoncync-0.1.tgz

 * Under the citoncync/ directory, copy the appropriate client script
   (citoncync-generic, citoncync-qnap, etc) to a file named "citoncync" in the
   same directory

 * Set citoncync to mode 755 (writable by owner, readable and executable
   to all):

   chmod 755 citoncync

 * Edit the new citoncync file and update the following settings as needed:

MYSCRIPT   - The default name "citoncync" should be kept in most cases.


SCRIPTBASE - Must be set to point to the share folder containing your 
             citoncync installation.

             Example: SCRIPTBASE=/share/MD0_DATA/citoncync


SOURCEBASE - The base directory that your SOURCES reside under.
             Do not add a trailing / to this value.  If you prefer to
             define each source's full path (which will be matched on the
             destination side) you can set this to ""

             Example: SOURCEBASE=/share/MD0_DATA


SOURCES  - One or more local paths to replicate under SOURCEBASE.  Do NOT add
           a trailing / to these paths.

           Example: SOURCES=(Admin Sales)


DESTHOST - The FQDN (fully qualified domain name) of the destination host's
           outside IP

           Example: DESTHOST=backup.example.com


DESTPORT - The TCP port to connect to

	   Example: DESTPORT=22


DESTUSER - The username to login as.  The recommendation is to create a
           customer code and a hostname to use.  (Customers may have more than
	   one device, but each gets its own chroot directory on the server.)

           Example: DESTUSER=widgetcorp-bignas


DESTBASE - The base path on the destination to copy into.  If using a chrooted
           target with a "data" subfolder the default path is appropriate.

           Example: DESTBASE=/data


SPEEDPERCENT - The percentage of calculated bandwidth to set as our average
               transfer rate.  RSync does not hard-cap transfers so this will
               only help even out transfers.  A very simple bandwidth check is
               run using SSH at the start of each replication.  SPEEDPERCENT
               is then applied to calculate the average rate we want to
	       maintain.  Do not set to more than 90 without testing.

               Example: SPEEDPERCENT=50


SCHEDULE - The 5 item cron schedule for replication.  Enclose in quotes.
           The format is "MIN HOUR MONTHDAY MONTH WEEKDAY". See
	   "man 5 crontab" for more info.

           Example: SCHEDULE="10 18 * * *"


SYNCOPTS - RSync parameters to use.  The defaults includes are generally
           fine.  Please document any additional flags.  Note that the
           filter, source, destination, SSH, and bandwidth options are
           added outside of these options and do not need to be specified.

           Example:
            SYNCOPTS="-a --partial --partial-dir=.part --delete-after"


LOGFILE - The full path to a plain text log file to hold all output from the
          replication tasks for this script.  The default places the log file
          in the SCRIPTBASE directory.

          Example: LOGFILE=${SCRIPTBASE}/replication.log


LOGKEEP - The number of previous logs to keep.

          Example: LOGKEEP=31


CRONTAB - The crontab file to add our schedule line to.  If left blank you
          will need to manually schedule the job.

          Example: CRONTAB=/var/spool/cron/crontabs/root


CRONUSER - The user to run under for a shared crontab.  (/etc/crontab and
           files under /etc/cron.d on Debian based systems, for instance.)
           Leave set to "" unless you need to specify the user.

	   Example: CRONUSER="root"


CRONRESTART - The command to use to reload the crontab.  If left blank nothing
              will be run after updating the crontab.

	      Example: CRONRESTART="service cron restart"


 * From a shell on the client, enter the citoncync folder

   Example:  cd /share/MD0_DATA/citoncync

 * Run citoncync with the showconfig option to display settings and generate
   then display a RSA SSH public key

   ./citoncync showconfig

 * Copy the text between the "--- CUT HERE ---" lines and then paste them
   into the authorized_keys list for your client machine's account on the
   server side.  (In FreeNAS this is in the "Modify" option for the account)

 * Copy "rsync-filter.example" to "rsync-filter".  If you want only certain
   files or folders to be replicated you need to modify rsync-filter.
   See the rsync man page for details.  The default filter file does not
   apply any filtering.

 * (Optional) Run our speedtest to see what citoncync will be using as
   its average bandwidth rate limit.  The speedtest runs each time replication
   is run and the rate averaging is based on the results modified by your
   SPEEDPERCENT setting.

   ./citoncync speedtest

 * Run the citoncync script with the "replicate" option to perform the initial
   data sync.

   ./citoncync replicate

 * Run citoncync with the "schedule" option to add a crontab entry, scheduling
   the script to run

   ./citoncync schedule

 * Besides replicating data, each source device has a .citoncync folder under
   its home directory on the target server that includes complete copy of the
   client's "citoncync" folder, including logs.  This can be used with the
   server/citoncync-repreport script to generate a regular report on sync
   activity from all clients


SERVER INSTALLATION
-------------------

TBD

