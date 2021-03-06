"""
Initialization and package-wide constants.

Author: Brian N West (bnwest@rice.edu)
copyright (C) 2010, Rice University. All rights reserved.

This software is subject to the provisions of the GNU Lesser General
Public License Version 2.1 (LGPL).  See LICENSE.txt for details.
"""

from zope.i18nmessageid import MessageFactory
from Products.CMFCore.utils import ToolInit
from Products.CMFCore.DirectoryView import registerDirectory
from Globals import package_home

from config import GLOBALS, PROJECTNAME, SKINS_DIR

messageFactory = MessageFactory('rhaptossword')

registerDirectory(config.SKINS_DIR, config.GLOBALS)

import SwordTool
tools = (SwordTool.SwordTool,)

def initialize(context):
    # Tool registration
    # (seems UNNECESSARY with the GenericSetup toolset registration, but every other product
    #  does this, so we will too--belt and suspenders. Plus, it gets us an icon.)
    ToolInit('Rhaptos Sword Tool', tools=tools, icon='tool.gif').initialize(context)

from Extensions import Install  # check syntax on startup
del Install
