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

import AccessControl

#from datetime import datetime, timedelta
#from socket import gethostname
#import os
#import transaction

# from getipaddr import getipaddr

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

    def __init__(self):
        """Initialize (singleton!) tool object."""
        # user configurable
        self.acceptingSwordRequests = True
        # unknown to the user
        log('__init__ completed.') # this no workeee


    security.declareProtected(ManagePermission, 'manage_sword_tool')
    def manage_sword_tool(self, acceptingSwordRequests=None):
        """
        Post creation configuration.  See manage_configure_sword_tool.zpt
        """
        # acceptingSwordRequests will either be the empty string or None
        # the empty string => the checkbox was checked
        # None => the checkbox was not checked
        acceptingSwordRequests = acceptingSwordRequests is not None
        self.acceptingSwordRequests = acceptingSwordRequests


    security.declareProtected(ManagePermission, 'getAcceptingRequests')
    def getAcceptingRequests(self):
        """Get process requests."""
        return self.acceptingSwordRequests


    security.declareProtected(ManagePermission, 'setAcceptingRequests')
    def setAcceptingRequests(self, acceptingSwordRequests):
        """Turn sword processing on and off."""
        self.acceptingSwordRequests = acceptingSwordRequests

