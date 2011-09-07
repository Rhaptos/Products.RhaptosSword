from xml.dom.minidom import parse
from zipfile import BadZipfile
from email import message_from_file
from StringIO import StringIO

from zope.interface import Interface, implements
from zope.publisher.interfaces.http import IHTTPRequest
from zope.component import adapts, queryAdapter, getMultiAdapter
from AccessControl import getSecurityManager
from Acquisition import aq_inner

from Products.CMFCore.utils import getToolByName
from Products.CMFCore.interfaces import IFolderish

from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from Products.CNXMLTransforms.helpers import OOoImportError, doTransform, makeContent

from rhaptos.atompub.plone.exceptions import PreconditionFailed
from rhaptos.atompub.plone.browser.atompub import ATOMPUB_CONTENT_TYPES
from rhaptos.swordservice.plone.browser.sword import PloneFolderSwordAdapter
from rhaptos.swordservice.plone.browser.sword import RetrieveContent
from rhaptos.swordservice.plone.browser.sword import EditMedia
from rhaptos.swordservice.plone.browser.sword import ISWORDContentUploadAdapter 
from rhaptos.swordservice.plone.browser.sword import ISWORDRetrieveContentAdapter
from rhaptos.swordservice.plone.interfaces import ISWORDEMIRI


class ValidationError(Exception):
    """ Basic validation error
    """

CNX_MD_NAMESPACE = 'http://cnx.rice.edu/mdml'

DCTERMS_NAMESPACE = "http://purl.org/dc/terms/"

OERDC_NAMESPACE = "http://cnx.org/aboutus/technology/schemas/oerdc"

METADATA_MAPPING =\
        {'title'               : 'title',
         'abstract'            : 'abstract',
         'language'            : 'language',
         'subject'             : 'keywords',
         'license'             : 'license',
         'descriptionOfChanges': 'descriptionOfChanges',
         'analyticsCode'       : 'GoogleAnalyticsTrackingCode',
        }

XSI_TYPE_TO_MDML_NAME_MAP =\
        {'oerdc:Subject': 'subject',
         'ISO639-1'     : 'language',
         'dcterms:URI'  : 'license',
        }

DESCRIPTION_OF_CHANGES =\
        {'derive': 'Derived a copy.',
         'checkout': 'Checked out a copy.'
        }

DESCRIPTION_OF_TREATMENT =\
        {'derive': 'Checkout and derive a new copy.',
         'checkout': 'Checkout to users workspace.',
        }

ROLE_NAMES = ['creator',
              'maintainer',
              'rightsHolder',
              'editor',
              'translator',
             ]

class IRhaptosWorkspaceSwordAdapter(ISWORDContentUploadAdapter):
    """ Marker interface for SWORD service specific to the Rhaptos 
        implementation.
    """


class IRhaptosContentRetrieveAdapter(ISWORDRetrieveContentAdapter):
    """ Marker interface for SWORD service specific to the Rhaptos 
        implementation.
    """


class IRhaptosEditMediaAdapter(ISWORDEMIRI):
    """ Marker interface for EM-IRI adapter specific to Rhaptos. """


class RhaptosWorkspaceSwordAdapter(PloneFolderSwordAdapter):
    """ Rhaptos specific implement of the SWORD folder adapter.
    """
    adapts(IFolderish, IHTTPRequest)

    # keep a handle on what changed during the process
    descriptionOfChanges = ''
    # keep a handle on the treatment of the object
    treatment = ''
    
    def generateFilename(self, name):
        """ Override this method to provide a more sensible name in the
            absence of content-disposition. """
        return self.context.generateUniqueId(type_name='Module')

    def _splitRequest(self, request):
        """ This is only to be used for multipart uploads. The first
            part is the atompub bit, the second part is the payload. """
        request.stdin.seek(0)
        message = message_from_file(request.stdin)
        atom, payload = message.get_payload()

        # Call get_payload with decode=True, so it can handle the transfer
        # encoding for us, if any.
        atom = atom.get_payload(decode=True)
        payload = payload.get_payload(decode=True)

        return atom, payload


    def createObject(self, context, name, content_type, request):
        # see if the request has a atompub payload that specifies,
        # module id in "source" or "mdml:derived_from" in ATOM entry.

        def _deriveOrCheckout(dom):
            # Check if this is a request to derive or checkout a module
            elements = dom.getElementsByTagNameNS(
                "http://purl.org/dc/terms/", 'source')
            if len(elements) > 0:
                # now we can fork / derive the module
                obj = self.deriveModule(
                    str(elements[0].firstChild.nodeValue))
                self.setActionMetadata(obj, action='derive')
                return obj
            elements = dom.getElementsByTagNameNS(
                "http://purl.org/dc/terms/", 'isVersionOf')
            if len(elements) > 0:
                obj = self.checkoutModule(
                    str(elements[0].firstChild.nodeValue))
                self.setActionMetadata(obj, action='checkout')
                return obj

        if content_type in ATOMPUB_CONTENT_TYPES:
            # find our marker elements
            body = request.get('BODYFILE')
            body.seek(0)
            dom = parse(body)
            body.seek(0)

            # Derive or checkout, if the headers are right
            obj = _deriveOrCheckout(dom)
            if obj is not None:
                return obj
        elif content_type.startswith('multipart/'):
            atom, payload = self._splitRequest(request)
            dom = parse(StringIO(atom))
            obj = _deriveOrCheckout(dom)
            if obj is not None:
                return obj

        return super(RhaptosWorkspaceSwordAdapter, self).createObject(
            context, name, content_type, request)


    def deriveModule(self, url):
        """ We checkout the object, fork it, remove the temp one and 
            return the forked copy.
        """
        module_id = url.split('/')[-1]
        # Fetch module and area
        version = 'latest'
        content_tool = getToolByName(self.context, 'content')
        module = content_tool.getRhaptosObject(module_id, version)
        area = self.context
        # We create a copy that we want to clean up later, let's track the id
        to_delete_id = area.generateUniqueId()
        area.invokeFactory(id=to_delete_id, type_name=module.portal_type)
        obj = area._getOb(to_delete_id)

        # module must be checked out to area before a fork is possible
        obj.setState('published')
        obj.checkout(module.objectId)

        # Do the fork
        forked_obj = obj.forkContent(
            license=module.getDefaultLicense(), return_context=True,
        )
        forked_obj.setState('created')
        forked_obj.setGoogleAnalyticsTrackingCode(None)

        # Delete temporary copy
        if to_delete_id:
            area.manage_delObjects(ids=[to_delete_id])
        return forked_obj


    def checkoutModule(self, url):
        context = aq_inner(self.context)
        module_id = url.split('/')[-1]
        # Fetch module
        content_tool = getToolByName(self.context, 'content')
        module = content_tool.getRhaptosObject(module_id, 'latest')

        if module_id not in context.objectIds():
            context.invokeFactory(id=module_id, type_name=module.portal_type)
            obj = context._getOb(module_id)
            obj.setState('published')
            obj.checkout(module.objectId)
            return obj
        else:
            obj = context._getOb(module_id)
            if obj.state == 'published':
                # Check out on top of published copy
                obj.checkout(module.objectId)
                return obj
            elif obj.state == "checkedout" and obj.version == module.version:
                # Already checked out, use as is
                return obj
            else:
                raise PreconditionFailed, "Cannot overwrite existing content"


    def updateMetadata(self, obj, fp):
        """ Metadata as described in:
            SWORD V2 Spec for Publishing Modules in Connexions
            Section: Metadata
        """
        dom = parse(fp)
        metadata = self.getMetadata(dom, METADATA_MAPPING)
        # better make sure we have a title while deriving content
        metadata.setdefault('title', obj.title)
        # we remove descriptionOfChanges because the update_metadata
        # script cannot cope with it.
        descriptionOfChanges = metadata.pop(
            'descriptionOfChanges', self.descriptionOfChanges)
        if descriptionOfChanges:
            obj.logAction('create', descriptionOfChanges)
            setattr(obj, 'description_of_changes', descriptionOfChanges)
        setattr(obj, 'treatment', self.treatment)
        obj.update_metadata(**metadata)
        # IB: Always add? Or replace when modifying existing content?
        self.addRoles(obj, dom)
        obj.reindexObject(idxs=metadata.keys())

    def updateContent(self, obj, fp):
        kwargs = {
            'original_file_name': 'sword-import-file',
            'user_name': getSecurityManager().getUser().getUserName()
        }
        text, subobjs, meta = doTransform(obj, "zip_to_folder",
            fp.read(), meta=1, **kwargs)
        # For a new document, it will contain a blank index.cnxml. For
        # existing documents, we want to replace all of it anyway. Either
        # way, we want to  delete the contents of the module and replace
        # it. Unless we have no text, then leave the default empty
        # document alone
        obj.manage_delObjects(
            filter(lambda x: x!=obj.default_file, obj.objectIds()))
        if text:
            obj.manage_delObjects([obj.default_file,])
            obj.invokeFactory('CNXML Document', obj.default_file,
                file=text, idprefix='zip-')
        makeContent(obj, subobjs)
        # make sure that the cnxml is the latest version
        obj.getDefaultFile().upgrade()

    def updateObject(self, obj, filename, request, response, content_type):
        obj = obj.__of__(self.context)
        if content_type in ATOMPUB_CONTENT_TYPES:
            body = request.get('BODYFILE')
            body.seek(0)
            self.updateMetadata(obj, body)
        elif content_type == 'application/zip':
            body = request.get('BODYFILE')
            body.seek(0)
            self.updateContent(obj, body)
        elif content_type.startswith('multipart/'):
            atom, payload = self._splitRequest(request)
            self.updateMetadata(obj, StringIO(atom))
            self.updateContent(obj, StringIO(payload))

        return obj


    def getMetadata(self, dom, mapping):
        """
        TODO:
            Set the attribution_note on the module.
            Investigate using 'getLanguagesWithoutSubtypes' and
            'getLanguageWithSubtypes' instead of sql call.

        """
        mdt = getToolByName(self.context, 'portal_moduledb')
        headers = self.getHeaders(dom, mapping)
        metadata = {}
        for key, value in headers:
            if key == 'license':
                mdt = getToolByName(self.context, 'portal_moduledb')
                mdt.getLicenseData(value)
            if key == 'keywords':
                value = value.split('\n')
            if key == 'language':
                plt = getToolByName(self.context, 'portal_languages')
                languages = plt.getAvailableLanguages()
                if value not in languages.keys():
                    raise ValidationError('The language %s is not valid.' %value)
            if key == 'subject':
                values = value.split('\n')
                subjects = mdt.sqlGetTags(scheme='ISKME subject').tuples()
                subjects = [tup[1].lower() for tup in subjects]
                for v in values:
                    if v.lower() not in subjects:
                        raise ValidationError('The subject %s is invalid.' %v)

            if value: metadata[key] = value
        return metadata


    def getHeaders(self, dom, mappings): 
        headers = []
        for prefix, uri in dom.documentElement.attributes.items():
            for name in mappings.keys():
                temp_dict = {}
                values = dom.getElementsByTagNameNS(uri, name)
                # split the simple values from those with xsi types
                for v in values:
                    xsi_type = v.getAttribute('xsi:type')
                    temp_name = XSI_TYPE_TO_MDML_NAME_MAP.get(xsi_type, name)
                    temp_values = temp_dict.get(temp_name, [])
                    temp_values.append(v)
                    temp_dict[temp_name] = temp_values
                
                for key, values in temp_dict.items():
                    value = '\n'.join([str(v.firstChild.nodeValue).strip()\
                                       for v in values\
                                       if v.firstChild is not None]
                                     )
                    if value: headers.append((mappings[key], str(value)))

        return headers
   

    def _getNewRoles(self, dom):
        newRoles = {}
        for role in ROLE_NAMES:
            for namespace in [DCTERMS_NAMESPACE, OERDC_NAMESPACE]:
                for element in dom.getElementsByTagNameNS(namespace, role):
                    tmp_role = role.capitalize()
                    ids = newRoles.get(tmp_role, [])
                    ids.append(element.getAttribute('oerdc:id'))
                    newRoles[tmp_role] = ids
        return newRoles


    def addRoles(self, obj, dom):
        newRoles = self._getNewRoles(dom)
        user_role_delta = obj.generateCollaborationRequests(
                newUser=True, newRoles=newRoles)
        for p in user_role_delta.keys():
            collabs = list(obj.getCollaborators())
            if p not in collabs:
                obj.addCollaborator(p)
                obj.requestCollaboration(p, user_role_delta[p])


    def updateRoles(self, obj, dom):
        """
        Compute the updated roles
        - just the list of userids and roles in the xml
        Compute the deleted roles
        - collaborators that are currently on the object, but not in the xml
        Compute the cancelled roles
        - pending collaboration request for which there are no roles in the xml
        """
        updateRoles = self._getNewRoles(dom)
        deleteRoles = []
        cancelRoles = []

        pending_collaborations = obj.getPendingCollaborations()
        for user_id in pending_collaborations.keys():
            if user_id not in updateRoles.keys() and user_id != obj.Creator():
                cancelRoles.append(user_id)
        for user_id in obj.getCollaborators():
            if user_id not in updateRoles.keys() and user_id != obj.Creator():
                deleteRoles.append(user_id)

        obj.update_roles(updateRoles = updateRoles,
                         deleteRoles = deleteRoles,
                         cancelRoles = cancelRoles)

    
    def setActionMetadata(self, obj, action):
        self.descriptionOfChanges = DESCRIPTION_OF_CHANGES[action]
        self.treatment = DESCRIPTION_OF_TREATMENT[action]
        return obj


class RhaptosContentRetrieveAdapter(RetrieveContent):

    def __call__(self):
        return self.context.module_export(format='zip')

class RhaptosEditMedia(EditMedia):
    def PUT(self):
        """ PUT against an existing item should update it.
        """
        filename = self.request.get_header(
            'Content-Disposition', self.context.title)
        content_type = self.request.get_header('Content-Type')

        parent = self.context.aq_inner.aq_parent
        adapter = getMultiAdapter(
            (parent, self.request), IRhaptosWorkspaceSwordAdapter)
        adapter.updateObject(self.context, filename, self.request, self.request.response, content_type)
