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
from rhaptos.atompub.plone.exceptions import PreconditionFailed

from rhaptos.swordservice.plone.interfaces import ISWORDEditIRI
from rhaptos.swordservice.plone.interfaces import ISWORDServiceDocument
from rhaptos.swordservice.plone.browser.sword import SWORDStatementAdapter
from rhaptos.swordservice.plone.browser.sword import SWORDStatementAtomAdapter
from rhaptos.swordservice.plone.browser.sword import EditIRI as BaseEditIRI
from rhaptos.swordservice.plone.exceptions import BadRequest

from Products.RhaptosSword.adapters import IRhaptosWorkspaceSwordAdapter
from Products.RhaptosSword.adapters import METADATA_MAPPING
from Products.RhaptosSword.adapters import DCTERMS_NAMESPACE

from Products.RhaptosSword.exceptions import PublishUnauthorized, Unpublishable
from Products.RhaptosSword.utils import splitMultipartRequest, checkUploadSize
from Products.RhaptosSword.utils import SWORDTreatmentMixin, REQUIRED_METADATA


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

    def treatment(self):
        return self.get_treatment(self.context)

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

    def treatment(self):
        return self.get_treatment(self.context)


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

class CollectionEditIRI(EditIRI):

    depositreceipt = ViewPageTemplateFile('collection_depositreceipt.pt')

    def _handleGet(self, **kw):
        view = self.__of__(self.context)
        pt = self.depositreceipt.__of__(view)
        return pt(**kw)

    def original_url(self):
        return self.context.getParent().absolute_url()

    def treatment(self):
        message = \
        """A derived copy of Collection %s was created for editing.
           * You can <a href="%s">edit the collection here</a>.""" \
        % (self.context.getId(), self.context.absolute_url())
        return message

