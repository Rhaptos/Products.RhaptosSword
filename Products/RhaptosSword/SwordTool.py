"""
SwordTool.py - tool for managing Sword requests.

Author: Brian N West (bnwest@rice.edu)
copyright (C) 2010, Rice University. All rights reserved.

This software is subject to the provisions of the GNU Lesser General
Public License Version 2.1 (LGPL).  See LICENSE.txt for details.
"""

from Products.CMFCore.utils import UniqueObject
from OFS.SimpleItem import SimpleItem
from Globals import InitializeClass
from ZODB.PersistentList import PersistentList
from Products.PageTemplates.PageTemplateFile import PageTemplateFile
from Products.CNXMLDocument import XMLService
from Products.CNXMLTransforms.helpers import CNXML2JSON_XSL
from Products.CNXMLTransforms.helpers import MDML2JSON_XSL

import AccessControl

#from datetime import datetime, timedelta
#from socket import gethostname
#import os
#import transaction

# from getipaddr import getipaddr

# Allow the sword.cpy file access to zipfile.BadZipfile
from AccessControl import ModuleSecurityInfo
ModuleSecurityInfo('zipfile').declarePublic('BadZipfile')


ManagePermission = 'View management screens'

import zLOG
def log(msg, severity=zLOG.INFO):
    zLOG.LOG("SwordTool: ", severity, msg)

class SwordTool(UniqueObject, SimpleItem):
    """
    Tool for managing Sword requests.
    """

    id = 'sword_tool'
    meta_type = 'Sword Tool'

    manage_options = (({'label':'Overview', 'action':'manage_overview'},
                       {'label':'Configure', 'action':'manage_configure'}
                      )+ SimpleItem.manage_options
                     )
    manage_overview  = PageTemplateFile('zpt/manage_overview_sword_tool.zpt', globals())
    manage_configure = PageTemplateFile('zpt/manage_configure_sword_tool.zpt', globals())
    
    security = AccessControl.ClassSecurityInfo()

    acceptingSwordRequests = True
    maxUploadSize = 10 * 1024 * 1024 # 10 Megabyte

    def __init__(self):
        """Initialize (singleton!) tool object."""
        # user configurable
        self.acceptingSwordRequests = True
        self.maxUploadSize = 10 * 1024 * 1024 # 10 Megabyte
        # unknown to the user
        log('__init__ completed.') # this no workeee


    security.declareProtected(ManagePermission, 'manage_sword_tool')
    def manage_sword_tool(self, acceptingSwordRequests=None, maxUploadSize=None):
        """
        Post creation configuration.  See manage_configure_sword_tool.zpt
        """
        # acceptingSwordRequests will either be the empty string or None
        # the empty string => the checkbox was checked
        # None => the checkbox was not checked
        acceptingSwordRequests = acceptingSwordRequests is not None
        self.acceptingSwordRequests = acceptingSwordRequests

        if maxUploadSize is not None:
            self.maxUploadSize = int(maxUploadSize)


    security.declareProtected(ManagePermission, 'getAcceptingRequests')
    def getAcceptingRequests(self):
        """Get process requests."""
        return self.acceptingSwordRequests


    security.declareProtected(ManagePermission, 'getMaxUploadSize')
    def getMaxUploadSize(self):
        """ Get maximum upload size for sword POST/PUT requests. """
        return self.maxUploadSize


    security.declareProtected(ManagePermission, 'setAcceptingRequests')
    def setAcceptingRequests(self, acceptingSwordRequests):
        """Turn sword processing on and off."""
        self.acceptingSwordRequests = acceptingSwordRequests


    def setMaxUploadSize(self, maxUploadSize):
        """ Set the maximum upload size. """
        self.maxUploadSize = int(maxUploadSize)

    security.declarePublic('cnxml2json')
    def cnxml2json(self, content):
        return XMLService.transform(content, CNXML2JSON_XSL)

    security.declarePublic('mdml2json')
    def mdml2json(self, content):
        return XMLService.transform(content, MDML2JSON_XSL)
