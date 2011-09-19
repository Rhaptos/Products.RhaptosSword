from zope.interface import implements
from Acquisition import aq_inner
from Acquisition import Explicit
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

from Products.RhaptosSword.adapters import IRhaptosWorkspaceSwordAdapter
from Products.RhaptosSword.adapters import getSiteEncoding
from Products.RhaptosSword.adapters import METADATA_MAPPING

from Products.RhaptosSword.exceptions import PublishUnauthorized


# TODO: move all these strings to the relevant templates; make macros as required.
PREVIEW_MSG = \
"""You can <a href="%s/module_view">preview your module here</a> to see what it will look like once it is published."""

ACTIONS_MSG = \
"""Module '%s' was imported via the SWORD API."""

DESCRIPTION_OF_CHANGES = \
"""The current description of the changes you have made for this version of the module: "%s" """

AUTHOR_AGREEMENT = \
"""You (%s, account:%s), will need to <a href="%s/module_publish">sign the license here.</a>"""

CONTRIBUTOR_AGREEMENT = \
"""Contributor, %s (account:%s), must <a href="%s/collaborations?user=%s">agree to be listed on this module, and sign the license agreement here</a>."""
         
DESCRIPTION_CHANGES_WARNING = \
"""You must <a href="%s">describe the changes that you have made to this version</a> before publishing."""

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
        
        treatment['description_of_changes'] = context.description_of_changes

        treatment['publication_requirements'] = \
            self.get_publication_requirements(context)
        return treatment


    def get_publication_requirements(self, context):
        encoding = self.getEncoding() 
        context_url = context.absolute_url()
        requirements = []
        if not context.license:
            for user_id in context.authors:
                user = self.pmt.getMemberById(user_id)
                if user:
                    fullname = user.getProperty('fullname')
                    req = AUTHOR_AGREEMENT %(fullname, user_id, context_url)
                    requirements.append(unicode(req, encoding))

        pending_collaborations = context.getPendingCollaborations()
        for user_id, collab in pending_collaborations.items():
            info = self.formatUserInfo(context, user_id) 
            requirements.append(unicode(info, encoding))

        if not context.description_of_changes:
            desc_of_changes_link = \
                context_url + '/module_description_of_changes'
            requirements.append(
                DESCRIPTION_CHANGES_WARNING % desc_of_changes_link)
        return requirements


    def formatUserInfo(self, context, user_id):
        user = self.pmt.getMemberById(user_id)
        fullname = user.getProperty('fullname')
        return CONTRIBUTOR_AGREEMENT % \
            (fullname, user_id, context.absolute_url(), user_id)


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
        # We have to commit the transaction, otherwise the object has a blank
        # _p_jar and cannot be moved. And if it cannot be moved it cannot be
        # published.
        transaction.commit()
        context = aq_inner(self.context)
        description_of_changes = context.message
        if self.canPublish():
            context.publishContent(message=description_of_changes)
        else:
            requirements = self.get_publication_requirements(context)
            raise PublishUnauthorized(
                "You do not have permission to publish this module",
                requirements)


    def _handlePut(self):
        """ PUT against an existing item should update it.
        """
        content_type = getContentType(self.request.get_header('Content-Type'))

        parent = self.context.aq_inner.aq_parent
        adapter = getMultiAdapter(
            (parent, self.request), IRhaptosWorkspaceSwordAdapter)

        if content_type in ATOMPUB_CONTENT_TYPES:
            body = self.request.get('BODYFILE')
            body.seek(0)
            merge = self.request.get_header(
                'HTTP_METADATA_SEMANTICS') and True or False
            if merge:
                # merge the metadata on the request with what is on the
                # module (in this case 'self.context')
                adapter.mergeMetadata(self.context, body)
            else:
                # replace what is on the module with metadata on the request
                # in the process all fields not on the request will be reset
                # on the module (see METADATA_DEFAULTS) for the values used.
                adapter.replaceMetadata(self.context, body)
            view = self.__of__(self.context)
            pt = self.depositreceipt.__of__(view)
            return pt()
        else:
            # This will result in a 400 error
            raise ValueError(
                "%s is not a valid content type for this request" % content_type)

    
    def canPublish(self):
        versioninfo = self.context.rmeVersionInfo()
        if self.context.publishBlocked(versioninfo):
            return False

        if self.pending_collaborations() or self.has_required_metadata():
            return False

        context = self.context
        try:
            published_version = \
                context.content.getRhaptosObject(context.id).latest.version
        except KeyError:
            published_version = None

        # Someone else has edited and published this object
        if published_version and (context.version != published_version):
            return False

        # You must specify at least one Author, Maintainer and Copyright
        # Holder.
        if not context.authors or not context.maintainers or \
           not context.licensors:
            return False

        if not context.validate():
            return False

        return True
    

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
        for key, value in METADATA_MAPPING.items():
            if not getattr(obj, key, None): return False
        return True

    
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
        for key, value in METADATA_MAPPING.items():
            if not getattr(obj, key, None):
                missing_metadata.append(key)
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
            wgurl = '%s/%s/sword' % (self.context.portal_url(), wg['link'])
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
