"""
Installation script for QuickInstaller use, including upgrades.
Facade for GenericSetup application.

Author: Brian N West (bnwest@rice.edu)
copyright (C) 2010, Rice University. All rights reserved.

This software is subject to the provisions of the GNU Lesser General
Public License Version 2.1 (LGPL).  See LICENSE.txt for details.
"""

from Products.RhaptosSword.config import PROJECTNAME, GLOBALS

from Products.CMFCore.utils import getToolByName

from StringIO import StringIO

import logging
logger = logging.getLogger('%s.Install' % PROJECTNAME)
def log(msg, out=None):
    logger.info(msg)
    if out: print >> out, msg
    print msg

def install(self):
    """Install method for this product. Runs GenericSetup application. If you do anything
    else, be sure to note that QuickInstaller is the only method available for install in
    the README.

    It should be kept idempotent; running it at any time should be safe. Also, necessary
    upgrades to existing data should be accomplished with a reinstall (running this!) if
    at all possible.
    """
    out = StringIO()
    log("Starting %s install" % PROJECTNAME, out)

    urltool = getToolByName(self, 'portal_url')
    portal = urltool.getPortalObject()

    # setup tool prep
    setup_tool = getToolByName(portal, 'portal_setup')
    prevcontext = setup_tool.getImportContextID()
    setup_tool.setImportContext('profile-CMFPlone:plone')   # get Plone steps registered, in case they're not
    setup_tool.setImportContext('profile-Products.%s:default' % PROJECTNAME)  # our profile and steps

    # run all import steps
    steps = ('toolset','skins',)
    for step in steps:
        log(" - applying step: %s" % step, out)
        status = setup_tool.runImportStep(step)
        log(status['messages'][step], out)
    # FIXME: we want to be able to just run all instead, but RhaptosSite setup step is not idempotent
    #status = setup_tool.runAllImportSteps()
    #log(status['messages'], out)

    # setup tool "teardown"
    setup_tool.setImportContext(prevcontext)
    ctr = getToolByName(self, 'content_type_registry')
    ids = ctr.predicate_ids
    predicate_id = 'atom+xml'
    for predicate_id in ['atom+xml', 'atom+xml;type=entry', 'zip']:
        if predicate_id not in ids:
            ctr.addPredicate(predicate_id, 'major_minor')
            predicate = ctr.getPredicate(predicate_id)
            predicate.major = ['application',]
            predicate.minor = [predicate_id,]
            ctr.assignTypeName(predicate_id, 'Module')
        ctr.reorderPredicate(predicate_id, 0)

    log("Successfully installed %s." % PROJECTNAME, out)
    return out.getvalue()
