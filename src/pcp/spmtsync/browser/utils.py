import logging
import requests
import json

from zope.component import getUtility
from plone.registry. interfaces import IRegistry


def getLogger(logfilename='var/log/spmtsync.log'):
    logger = logging.getLogger('spmtsync')
    logger.setLevel(logging.DEBUG)
    # create file handler which logs even debug messages
    fh = logging.FileHandler(logfilename)
    fh.setLevel(logging.DEBUG)
    # create console handler with a higher log level
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    # create formatter and add it to the handlers
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_formatter = logging.Formatter(
        '%(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(file_formatter)
    ch.setFormatter(console_formatter)
    # add the handlers to the logger
    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


def getDataFromSPMT(url):
    """Returns the payload from url or None.
    Never fails."""
    if 'localhost' in url:
        registry = getUtility(IRegistry)
        SPMT_BASE = registry['pcp.spmtsync.baseurl']
        url = url.replace('localhost', SPMT_BASE)
    r = requests.get(url)
    d = json.loads(r.content)
    try:
        return d['data']
    except KeyError:
        # TODO add logging
        return None


def getServiceData():
    """return a list of dictionaries with the service data"""
    registry = getUtility(IRegistry)
    source_url = registry['pcp.spmtsync.portfoliourl']
    source = getDataFromSPMT(source_url)
    if source is not None:
        return source['services']
    return None


def email2puid(site):
    """
    Return a mapping email -> UID for all exisitng Person objects.
    If an email address occurs several times only the first hit is
    recorded and a warning is logged.
    """
    logger = logging.getLogger('contacts')
    result = {}
    for person in site.people.contentValues():
        email = person.getEmail().lower()
        uid = person.UID()
        if email and email in result.keys():
            logger.warning("'%s' already found - skipping" % email)
            continue
        logger.debug("Mapping '%s' to '%s'" % (email, uid))
        result[email] = uid
    return result.copy()
