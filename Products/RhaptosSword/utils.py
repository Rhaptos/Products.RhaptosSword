from StringIO import StringIO
from xml.dom.minidom import parse
from AccessControl import getSecurityManager
from email import message_from_file
from Products.CMFCore.utils import getToolByName
from rhaptos.swordservice.plone.exceptions import MaxUploadSizeExceeded

ACTIONS_MSG = \
"""Module '%s' was imported."""

# TODO: move all these strings to the relevant templates; make macros as required.
PREVIEW_MSG = \
"""You can <a href="%s/module_view">preview your module here</a> to see what it will look like once it is published."""

DESCRIPTION_OF_CHANGES = \
"""The current description of the changes you have made for this version of the module: "%s" """

AUTHOR_AGREEMENT = \
"""Author (%s, account:%s), will need to <a href="%s/module_publish">sign the license here.</a>"""

COLABORATION_WARNING = \
"""Contributor, %s (account:%s, email:%s), must <a href="%s/collaborations?user=%s">agree to be associated with this module</a>."""
         
DESCRIPTION_CHANGES_WARNING = \
"""You must <a href="%s">describe the changes that you have made to this version</a> before publishing."""

NEW_LICENSE_WARNING = \
"""The publication license agreement has changed since you last agreed to it.
The previous license on this content was %s. You will need to <a
href="%s/module_publish">accept the new license prior to publishing</a>."""

NO_TITLE_WARNING = \
"""PUBLISH BLOCKED: This object has an invalid title. You will not be able to
publish until you enter a title on the <a href="%s/module_metadata">metadata
page</a>."""

CNXML_INVALID_WARNING = \
"""The module did not validate. Please fix before publishing.
<a href="%s/module_publish_description">See the errors</a>."""

CNXML_VERSION_WARNING = \
"""You need to <a href="%s/cc_license_prepub">upgrade this module</a> to
version 0.7 before you can publish it or make metadata changes."""

MODULE_VERSION_WARNING = \
"""PUBLISH BLOCKED: This module is unpublishable in its current state because
it has been superseded by later revisions. To fix this problem, use the
<a href="%s/diff">View Changes</a> feature to make a note of the work you have
done on this copy of the module; then <a href="%s/confirm_discard">discard the
module and check out a fresh copy to edit.  Details: This copy of the module is
based on version %s, but the current published version is %s."""

AUTHOR_WARNING = \
"""Authors: There are currently no Authors! You must add one before previewing
or publishing."""

COPYHOLDERS_WARNING = \
""" Copyright Holders: There are currently no Copyright Holders! You must
add one before previewing or publishing."""

NOMAINTAINER_WARNING = \
"""Maintainers: There are currently no Maintainers! You must add one before
previewing or publishing."""

PERMISSION_WARNING = \
"""PUBLISH BLOCKED: You do not have maintainer permissions on the published
version of this object, so you will not be able to publish the current
revision. Other options are to <a href="%s/module_send_patch">suggest your
edits</a> to the module's maintainers, or <a href="%s/confirm_fork">derive your
own copy</a> based on this module."""

REVIEW_WARNING = \
"""
This item will be submitted for publication.<br />
NOTE: Due to an increase of spam on our site:
<ul>
<li>The first publish of a new author is held to ensure it does not violate the Site User Agreement.</li>
<li>Once your content is accepted and published, subsequent publishes will not have to be held.</li>
<li>We appreciate your patience with this policy.</li>
</ul>
"""

REQUIRED_METADATA = ['title', 'subject',]

def splitMultipartRequest(request):
    """ This is only to be used for multipart uploads. The first
        part is the atompub bit, the second part is the payload. """
    request.stdin.seek(0)
    message = message_from_file(request.stdin)
    atom, payload = message.get_payload()

    # Call get_payload with decode=True, so it can handle the transfer
    # encoding for us, if any.
    atom = atom.get_payload(decode=True)
    content_type = payload.get_content_type()
    payload = payload.get_payload(decode=True)
    dom = parse(StringIO(atom))
    return dom, payload, content_type


def checkUploadSize(context, fp):
    """ Check size of file handle. """
    maxupload = getToolByName(context, 'sword_tool').getMaxUploadSize()
    if hasattr(fp, 'seek'):
        fp.seek(0, 2)
        size = fp.tell()
        fp.seek(0)
    else:
        size = len(fp)
    if size > maxupload:
        raise MaxUploadSizeExceeded("Maximum upload size exceeded",
            "The uploaded content is larger than the allowed %d bytes." % maxupload)


def getSiteEncoding(context):
    """ if we have on return it,
        if not, figure out what it is, store it and return it.
    """
    encoding = 'utf-8'
    properties = getToolByName(context, 'portal_properties')
    site_properties = getattr(properties, 'site_properties', None)
    if site_properties:
        encoding = site_properties.getProperty('default_charset')
    return encoding

    

class SWORDTreatmentMixin(object):

    encoding = None


    def __init__(self, context, request):
        self.pmt = getToolByName(self.context, 'portal_membership')


    def getEncoding(self):
        """ Get the encoding to use.
            We prefer the site encoding, but will fall back to utf-8
        """
        if not self.encoding:
            self.encoding = getSiteEncoding(self.context)
        return self.encoding
    

    def get_treatment(self, context):
        treatment = {}

        module_name = context.title
        treatment['actions'] = ACTIONS_MSG % module_name

        treatment['preview_link'] = \
            PREVIEW_MSG %context.absolute_url()
        
        treatment['description_of_changes'] = context.message

        if context.state == 'published':
            # No requirements if we are already published
            treatment['publication_requirements'] = []
        else:
            treatment['publication_requirements'] = \
                self.get_publication_requirements(context)

            # If user does not have publisher rights, add something here
            # to tell him that it has been submitted for review. This is seperate
            # from get_publication_requirements because it is not a hard
            # requirement for attempting to publish, while all the other cases
            # are.
            if not self.pmt.checkPermission('Publish Rhaptos Object', context):
                treatment['publication_requirements'].append(
                    unicode(REVIEW_WARNING, self.getEncoding()))

        return treatment


    def get_publication_requirements(self, context):
        """ Things we need to check for (including but likely not limited to):
            1. License is signed
            2. Title is properly set
            3. Module has xml and it is valid
            4. CNXML version must be current
            5. versioned-from must match the current published module
            6. module has at least one maintainer/copyright holder/author
            7. Latest by-CC agreed to
            8. All contributors have agreed to license
            9. No pending role requests/removals
            10. A description of changes have been added
            11. User has the publisher role
            12. User has permission to publish
        """
        def formatUserInfo(user_id):
            # TODO: wrap in error handling decorator.
            user = self.pmt.getMemberById(user_id)
            if user:
                fullname = user.getProperty('fullname')
                email = user.getProperty('email')
                return COLABORATION_WARNING % \
                    (fullname, user_id, email, context.absolute_url(), user_id)
            return ''

        encoding = self.getEncoding() 
        context_url = context.absolute_url()
        requirements = []
        # Items 1, 7 and 8
        if context.license:
            if context.license != context.getDefaultLicense():
                req = NEW_LICENSE_WARNING % (context.license, context.absolute_url())
                requirements.append(unicode(req, encoding))
        else:
            for user_id in context.authors:
                user = self.pmt.getMemberById(user_id)
                if user:
                    fullname = user.getProperty('fullname')
                    req = AUTHOR_AGREEMENT %(fullname, user_id, context_url)
                    requirements.append(unicode(req, encoding))

        # Item 2
        title = context.title
        if not title or title == '(Untitled)':
            requirements.append(
                unicode(NO_TITLE_WARNING % context.absolute_url(), encoding))

        # Item 3
        # validate returns an empty list if all is fine, so the meaning of this
        # is inverted. Negated. All the wrong way upside down.
        if context.validate():
            requirements.append(unicode(
                CNXML_INVALID_WARNING % context.absolute_url(), encoding))

        # Item 4
        # Hard-coding of 0.7. Its already done in too many places :-(
        cnxmlversion = context.getDefaultFile().getVersion()
        if cnxmlversion is not None and float(cnxmlversion) < 0.7:
            requirements.append(unicode(
                CNXML_VERSION_WARNING % context.absolute_url(), encoding))

        # Item 5
        content_tool = getToolByName(self.context, 'content')
        if context.objectId is None:
            pubobj = None
            published_version = None
        else:
            try:
                pubobj = content_tool.getRhaptosObject(context.objectId)
                published_version = pubobj.latest.version
            except KeyError:
                pubobj = None
                published_version = None

        if published_version and (context.version != published_version):
            requirements.append(unicode(
                MODULE_VERSION_WARNING % (context.absolute_url(),
                    context.absolute_url(), context.version, published_version),
                    encoding))

        # Item 6
        if not context.authors:
            requirements.append(unicode(AUTHOR_WARNING, encoding))
        if not context.maintainers:
            requirements.append(unicode(NOMAINTAINER_WARNING, encoding))
        if not context.licensors:
            requirements.append(unicode(COPYHOLDERS_WARNING, encoding))

        # Item 9
        pending_collaborations = context.getPendingCollaborations()
        for user_id, collab in pending_collaborations.items():
            info = formatUserInfo(user_id) 
            requirements.append(unicode(info, encoding))

        # Item 10
        if not context.message:
            desc_of_changes_link = \
                context_url + '/module_metadata#description_of_changes'
            requirements.append(
                DESCRIPTION_CHANGES_WARNING % desc_of_changes_link)

        # Item 12
        if pubobj is not None:
            haspermission = self.pmt.checkPermission('Edit Rhaptos Object', pubobj)
        else:
            cur_user = getSecurityManager().getUser().getUserName()
            haspermission = cur_user in context.maintainers or \
                self.pmt.checkPermission('Edit Rhaptos Object', context)

        if not haspermission:
            requirements.append(unicode(
                PERMISSION_WARNING % (context.absolute_url(),)*2, encoding))

        return requirements

    def is_pending(self, user_id):
        return user_id in self.context.pending_collaborations()

    def getLinkBase(self, module):
        """ This call will figure out what the state of the module is and supply
            a suggested base url
        """
        # would prefer to use module.isPublic, but not sure it's checking for the
        # correct state. Probably should be checking for 'published' not 'public'.
        if module.state == 'published':
            return self.getPublishedLinkBase(module)
        return self.getUnpublishedLinkBase(module)

    def getUnpublishedLinkBase(self, module):
        return module.absolute_url()

    def getPublishedLinkBase(self, module):
        content_tool = getToolByName(self.context, 'content')
        base_url = content_tool.absolute_url()
        return '%s/%s/%s' %(base_url, module.id, module.version)

    def pending_collaborations(self):
        return self.context.getPendingCollaborations()

    def get_user(self, userid):
        return self.pmt.getMemberById(userid)

    def get_roles(self, collaboration_requests):
        roles_and_users = {}
        for userid, collab_request in collaboration_requests.items():
            roles = collab_request.roles 
            for role, action in roles.items():
                userids = roles_and_users.get(role, '')
                userids = userids + ' %s' %userid
                roles_and_users[role] = userids
        return roles_and_users

    def has_required_metadata(self):
        obj = self.context.aq_inner
        for attr in REQUIRED_METADATA:
            value = getattr(obj, attr, None)
            if not value: return False
            if attr == 'title' and value == '(Untitled)':
                return False
        return True
    
    def creators(self, module):
        creator_set = set(module.creators)
        author_set = set(module.authors)
        return list(creator_set.union(author_set))

    def subject(self):
        return ', '.join(self.context.subject) 

    def derived_modules(self):
        return self.context.objectValues(spec='Module')
    
    def fullname(self, user_id):
        user = self.pmt.getMemberById(user_id)
        if user:
            return user.getProperty('fullname')
        return None

    def email(self, user_id):
        user = self.pmt.getMemberById(user_id)
        if user:
            return user.getProperty('email')
        return None

    def collaborators(self):
        pending_collabs = self.pending_collabs()
        collaborators = {'pending_collabs': pending_collabs, }
        return collaborators

    def pending_collabs(self):
        return self.context.getPendingCollaborations()

    def deposited_by(self):
        return ', '.join(self.context.authors)

    def entries(self):
        meta_types = ['CMF CNXML File', 'UnifiedFile',]
        return self.context.objectValues(spec=meta_types)
