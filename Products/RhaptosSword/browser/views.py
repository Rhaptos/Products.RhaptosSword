from StringIO import StringIO
from xml.dom.minidom import parse
from zope.interface import implements
from Acquisition import aq_inner
from Acquisition import Explicit
from AccessControl import getSecurityManager
import transaction

from zope.component import getMultiAdapter

from Products.CMFCore.utils import getToolByName

from Products.Five import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from rhaptos.atompub.plone.browser.atompub import ATOMPUB_CONTENT_TYPES
from rhaptos.atompub.plone.browser.atompub import getContentType
from rhaptos.swordservice.plone.interfaces import ISWORDEditIRI
from rhaptos.swordservice.plone.interfaces import ISWORDServiceDocument
from rhaptos.swordservice.plone.browser.sword import SWORDStatementAdapter
from rhaptos.swordservice.plone.browser.sword import SWORDStatementAtomAdapter
from rhaptos.swordservice.plone.browser.sword import EditIRI as BaseEditIRI
from rhaptos.swordservice.plone.exceptions import BadRequest

from Products.RhaptosSword.adapters import IRhaptosWorkspaceSwordAdapter
from Products.RhaptosSword.adapters import getSiteEncoding
from Products.RhaptosSword.adapters import METADATA_MAPPING
from Products.RhaptosSword.adapters import DCTERMS_NAMESPACE

from Products.RhaptosSword.exceptions import PublishUnauthorized
from Products.RhaptosSword.utils import splitMultipartRequest, checkUploadSize


# TODO: move all these strings to the relevant templates; make macros as required.
PREVIEW_MSG = \
"""You can <a href="%s/module_view">preview your module here</a> to see what it will look like once it is published."""

ACTIONS_MSG = \
"""Module '%s' was imported."""

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


class EditIRI(BaseEditIRI, SWORDTreatmentMixin, Explicit):
    """ This extends the SWORD v 2.0 Deposit Receipt to:
        - List role requests.
        - Show whether the license has been signed by the author and all
            contributors.
        - What contributors (see above: author, editor, etc), still need
            to accept their roles on the document.
        - Show whether all required metadata has been provided (including
            the ‘description-of-changes’ if this is a new version of
            existing content).

        TODO:
        Decide how to handle differences between "In-Progress: true" and
        "In-Progress: false" HTTP headers.
    """
    __name__ = "edit"
    implements(ISWORDEditIRI)

    depositreceipt = ViewPageTemplateFile('depositreceipt.pt')
    
    def __init__(self, context, request):
        BaseEditIRI.__init__(self, context, request)
        SWORDTreatmentMixin.__init__(self, context, request)
        Explicit.__init__(self)


    def _handleGet(self, **kw):
        view = self.__of__(self.context)
        pt = self.depositreceipt.__of__(view)
        return pt(**kw)


    def _handlePublish(self):
        context = aq_inner(self.context)
        if context.state == 'published':
            raise Unpublishable, "Module already published"

        # Call transaction.savepoint() to make _p_jar appear on
        # persistent objects, otherwise the object has a blank _p_jar
        # and cannot be moved. And if it cannot be moved it cannot be
        # published.
        transaction.savepoint(optimistic=True)

        requirements = self.get_publication_requirements(context)
        if not requirements:
            context.publishContent(message=context.message)
        else:
            raise PublishUnauthorized(
                "You do not have permission to publish this module",
                "<br />\n".join(requirements))


    def _handlePost(self):
        """ A POST fo the Edit-IRI can do one of two things. You can either add
            more metadata by posting an atom entry, you can add more data and
            metadata with a multipart post, or you can publish the module with
            an empty request and In-Progress set to false.
        """
        context = aq_inner(self.context)
        content_type = self.request.get_header('Content-Type', '')
        content_type = getContentType(content_type)

        if content_type in ATOMPUB_CONTENT_TYPES:
            # Apply more metadata to the item
            adapter = getMultiAdapter(
                (context.aq_parent, self.request), IRhaptosWorkspaceSwordAdapter)

            body = self.request.get('BODYFILE')
            body.seek(0)
            if context.state == 'published':
                context.checkout(self.context.objectId)
            adapter.updateMetadata(context, parse(body))
        elif content_type.startswith('multipart/'):
            checkUploadSize(context, self.request.stdin)
            atom_dom, payload, payload_type = splitMultipartRequest(self.request)

            cksum = self.request.get_header('Content-MD5')
            merge = self.request.get_header('Update-Semantics')
            adapter = getMultiAdapter(
                (context.aq_parent, self.request), IRhaptosWorkspaceSwordAdapter)

            if context.state == 'published':
                context.checkout(self.context.objectId)

            adapter.updateMetadata(context, atom_dom)
            adapter.updateContent(context, StringIO(payload), payload_type,
                cksum, merge == 'http://purl.org/oerpub/semantics/Merge')
            context.logAction(adapter.action)
        elif content_type:
            # A content type is provided, and its not atom+xml or multipart
            raise BadRequest(
                "You cannot POST content of type %s to the SE-IRI" % content_type)

        # If In-Progress is set to false or omitted, try to publish
        in_progress = self.request.get_header('In-Progress', 'false')
        if in_progress == 'false':
            self._handlePublish()
            # We SHOULD return a deposit receipt, status code 200, and the
            # Edit-IRI in the Location header.
            self.request.response.setHeader('Location',
                '%s/sword' % context.absolute_url())
            self.request.response.setStatus(200)

        view = context.unrestrictedTraverse('@@sword')
        return view._handleGet()


    def _handlePut(self):
        """ PUT against an existing item should update it.
        """
        content_type = self.request.get_header('Content-Type')
        if content_type is None:
            raise BadRequest("You have no Content-Type header in your request")
        content_type = getContentType(content_type)

        if content_type in ATOMPUB_CONTENT_TYPES or \
          content_type.startswith('multipart/'):
            # If the module is published, do a transparent checkout
            if self.context.state == 'published':
                self.context.checkout(self.context.objectId)

            merge = self.request.get_header(
                'Update-Semantics') and True or False
            parent = self.context.aq_inner.aq_parent
            adapter = getMultiAdapter(
                (parent, self.request), IRhaptosWorkspaceSwordAdapter)

            if content_type.startswith('multipart/'):
                atom_dom, payload, payload_type = splitMultipartRequest(
                    self.request)
                checkUploadSize(self.context, payload)

                # Update Content
                cksum = self.request.get_header('Content-MD5')
                adapter.updateContent(self.context, StringIO(payload),
                    payload_type, cksum, merge)
                self.context.logAction(adapter.action)
            else:
                body = self.request.get('BODYFILE')
                checkUploadSize(self.context, body)
                atom_dom = parse(body)

            # update Metadata
            if merge:
                # merge the metadata on the request with what is on the
                # module (in this case 'self.context')
                adapter.mergeMetadata(self.context, atom_dom)
            else:
                # replace what is on the module with metadata on the request
                # in the process all fields not on the request will be reset
                # on the module (see METADATA_DEFAULTS) for the values used.
                adapter.replaceMetadata(self.context, atom_dom)

            # If In-Progress is set to false or omitted, try to publish
            if self.request.get_header('In-Progress', 'false') == 'false':
                self._handlePublish()

            # response code of 200 as required by SWORD spec:
            self.request.response.setStatus(200)
            # set the location header
            self.request.response.setHeader(
                'Location',
                '%s/sword' %self.context.absolute_url())

            view = self.__of__(self.context)
            pt = self.depositreceipt.__of__(view)
            return pt()
        else:
            # This will result in a 400 error
            raise ValueError(
                "%s is not a valid content type for this request" % content_type)


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


    def treatment(self):
        return self.get_treatment(self.context)


    def email(self, user_id):
        user = self.pmt.getMemberById(user_id)
        if user:
            return user.getProperty('email')
        return None


class AtomFeed(BrowserView):
    """
    """
    def getAuthors(self):
        authors = getattr(self.context, 'authors', '')
        return ' '.join(authors)

    
    def getLicense(self):
        license = getattr(self.context, 'license', None)
        return license


    def entries(self):
        meta_types = ['CMF CNXML File', 'UnifiedFile',]
        return self.context.objectValues(spec=meta_types)


class RhaptosSWORDStatement(SWORDStatementAdapter, SWORDTreatmentMixin):

    statement = ViewPageTemplateFile('statement.pt')

    def __init__(self, context, request):
        SWORDStatementAdapter.__init__(self, context, request)
        SWORDTreatmentMixin.__init__(self, context, request)

        self.missing_metadata = self.check_metadata()
        self.has_required_metadata = True
        if not self.missing_metadata: self.has_required_metadata = False


    def check_metadata(self):
        obj = self.context.aq_inner
        missing_metadata = []
        for attr in REQUIRED_METADATA:
            value = getattr(obj, attr, None)
            if not value:
                missing_metadata.append(attr)
            if attr == 'title' and value == '(Untitled)':
                missing_metadata.append(attr)
        return missing_metadata


    def collaborators(self):
        pending_collabs = self.pending_collabs()
        collaborators = {'pending_collabs': pending_collabs, }
        return collaborators
    

    def pending_collabs(self):
        return self.context.getPendingCollaborations()


    def treatment(self):
        return self.get_treatment(self.context)


    def deposited_by(self):
        return ', '.join(self.context.authors)


    def entries(self):
        meta_types = ['CMF CNXML File', 'UnifiedFile',]
        return self.context.objectValues(spec=meta_types)


class RhaptosSWORDStatementAtom(SWORDStatementAtomAdapter):
    """
    """
    
    # we override the atom page template, since the Rhaptos SWORD atom content
    # is quite distinct from the plain SWORD atom feed content.
    atom = ViewPageTemplateFile('atom.pt')

    def getAuthors(self):
        authors = getattr(self.context, 'authors', '')
        return ' '.join(authors)

    
    def getLicense(self):
        license = getattr(self.context, 'license', None)
        return license


    def entries(self):
        meta_types = ['CMF CNXML File', 'UnifiedFile',]
        return self.context.objectValues(spec=meta_types)


class ServiceDocument(BrowserView):
    """ Rhaptos Service Document """

    __name__ = "servicedocument"
    implements(ISWORDServiceDocument)

    servicedocument = ViewPageTemplateFile('servicedocument.pt')

    def __call__(self):
        return self.servicedocument()

    @property
    def maxuploadsize(self):
        """ Returns the maximum file size we will accept. """
        return getToolByName(self.context, 'sword_tool').getMaxUploadSize()

    def collections(self):
        """ Return home folder and workgroups we have access too """
        result = []
        pmt = getToolByName(self.context, 'portal_membership')
        member = pmt.getAuthenticatedMember()
        homefolder = pmt.getHomeFolder(member.getId())
        result.append({
            'url': homefolder.absolute_url(),
            'title': homefolder.Title(),
            'description': homefolder.Description()
            }
        )
        for wg in self.context.getWorkspaces():
            wgurl = '%s/%s' % (self.context.portal_url(), wg['link'])
            members = ', '.join([m['id'] for m in wg.get('members', [])])
            result.append({
                'url': wgurl,
                'title': wg['title'],
                'description': wg['description'],
                'members': members,
                }
            )
        return result

    def portal_title(self):
        """ Return the portal title. """
        return getToolByName(self.context, 'portal_url').getPortalObject().Title()


class ContentSelectionLensEditIRI(EditIRI):
    def _handleGet(self, **kw):
        raise NotImplementedError(
            'GET not implemented for %s.' %self.context.__module__)

    def _handlePost(self):
        lens = self.context
        if not lens.isOpen():
            # get attrs
            encoding = self.getEncoding() 
            content_tool = getToolByName(self.context, 'content')
            dom = parse(self.request.get('BODYFILE'))
            path = lens.getPhysicalPath()
            
            # get all the modules
            entries = dom.getElementsByTagName('entry')
            for entry in entries:
                links = entry.getElementsByTagName('link')
                module_link = links and links[0]
                contentLink = module_link and \
                    module_link.getAttribute('href').strip().encode(encoding)
                contentId = contentLink.split('/')[-1]
                if contentId:
                    module = content_tool.getRhaptosObject(contentId)
                    if module:
                        version = module.latest.version or 'latest'
                        namespaceTags = []
                        tags = ''
                        comment = 'Added via SWORD API'
                        lens.lensAdd(
                            lensPath=path, 
                            contentId=contentId, 
                            version=version, 
                            namespaceTags=namespaceTags, 
                            tags=tags,
                            comment=comment,
                        )            
            return lens
        else:
            # actually we should raise and error and use the decorators
            return None

    def _handlePut(self):
        raise NotImplementedError(
            'PUT not implemented for %s.' %self.context.__module__)


class CollectionEditIRI(EditIRI):

    depositreceipt = ViewPageTemplateFile('collection_depositreceipt.pt')

    def _handleGet(self, **kw):
        view = self.__of__(self.context)
        pt = self.depositreceipt.__of__(view)
        return pt(**kw)
