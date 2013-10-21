#!python

# Copyright 2013, Citon Computer Corporation
# Author: Paul Hirsch

# citoncync-repreport - Scan a given "basepath" directory for one or more
#                       CitonCync customer subdirectories then report to
#                       one or more email addresses on last sync, data usage
#                       and other fun facts.

## Imports
# General
import sys, os, errno, traceback, time, re, datetime

# Configuration
import ConfigParser     # XXX - Change this to "configparser" for Python 3
import optparse

# Reporting via email
import smtplib, email


# Handy lambda to pretty print file sizes - From Anonymous post to
# http://www.5dollarwhitebox.org/drupal/node/84
humansize = lambda s:[(s%1024**i and "%.1f"%(s/1024.0**i) or str(s/1024**i))
+x.strip() for i,x in enumerate(' KMGTPEZY') if s<1024**(i+1) or i==8][0]

def parseArgs ():
    """
    Take in command line options
    """
    
    

def listCustomers (basepath,dirmatch,ignorecusts):
    """
    List customer parent directories under basepath, ignoring anything that
    does not start with the dirmatch pattern or anything inside
    the ignorecusts array.  Returns array of customers.
    """

    customers = []

    for cust in os.listdir(basepath):
        m = re.match(dirmatch, cust)
        if m:
            if ignorecusts.count(cust) == 0:
                customers.append
    
    return customers


def listCustomerHosts (basepath,customer,dirmatch):
    """
    List customer's hosts, ignoring anything that does not start with the
    dirmatch pattern. Returns array of host directory names.
    """

    hostdirs = []

    for hostn in os.listdir(os.path.join(basepath, customer)):
        m = re.match(dirmatch, hostn)

        if m:
            hostdirs.append(hostn)

    return hostdirs


def getFreeSpace(folder):
    """ 
    Return folder/drive free space (in bytes) - UNIX Only
    """
    return os.statvfs(folder).f_bfree * os.statvfs(folder).f_frsize



def main ():
    
    proctime = time.time()



    


if __name__ = '__main__':
    main()
