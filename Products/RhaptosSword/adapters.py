from copy import copy
from xml.dom.minidom import parse
from zipfile import BadZipfile
from email import message_from_file
from StringIO import StringIO
from types import StringType, ListType, TupleType
import md5
import os
from zipfile import ZipFile, BadZipfile

from zope.interface import Interface, implements
from zope.publisher.interfaces.http import IHTTPRequest
from zope.component import adapts, queryAdapter, getMultiAdapter
from AccessControl import getSecurityManager
from Acquisition import aq_inner
from zExceptions import Unauthorized

from Products.CMFCore.utils import getToolByName
from Products.CMFCore.interfaces import IFolderish

from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from Products.CNXMLTransforms.helpers import OOoImportError, doTransform, makeContent

from rhaptos.atompub.plone.exceptions import PreconditionFailed
from rhaptos.atompub.plone.browser.atompub import ATOMPUB_CONTENT_TYPES
from rhaptos.swordservice.plone.browser.sword import PloneFolderSwordAdapter
from rhaptos.swordservice.plone.browser.sword import EditMedia
from rhaptos.swordservice.plone.browser.sword import ISWORDContentUploadAdapter 
from rhaptos.swordservice.plone.browser.sword import show_error_document
from rhaptos.swordservice.plone.interfaces import ISWORDEMIRI
from rhaptos.swordservice.plone.exceptions import MaxUploadSizeExceeded
from rhaptos.swordservice.plone.exceptions import ErrorChecksumMismatch
from rhaptos.swordservice.plone.exceptions import BadRequest

from Products.RhaptosSword.normalize import normalizeFilename
from Products.RhaptosSword.exceptions import CheckoutUnauthorized
from Products.RhaptosSword.exceptions import OverwriteNotPermitted
from Products.RhaptosSword.exceptions import TransformFailed


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

    
class ValidationError(Exception):
    """ Basic validation error
    """

CNX_MD_NAMESPACE = "http://cnx.rice.edu/mdml"

DCTERMS_NAMESPACE = "http://purl.org/dc/terms/"

OERDC_NAMESPACE = "http://cnx.org/aboutus/technology/schemas/oerdc"

METADATA_MAPPING =\
        {'title': 'title',
         'abstract': 'abstract',
         'language': 'language',
         'subject': 'keywords',
         'oer-subject': 'subject',
         'descriptionOfChanges': 'description_of_changes',
         'analyticsCode': 'GoogleAnalyticsTrackingCode',
        }

METADATA_DEFAULTS = \
        {'title': '(Untitled)',
         'abstract': '',
         'language': 'en',
         'keywords': [],
         'subject': [],
         'description_of_changes': 'Created Module',
         'GoogleAnalyticsTrackingCode': '',
        }

DESCRIPTION_OF_CHANGES =\
        {'derive': 'Derived a copy.',
         'checkout': 'Checked out a copy.'
        }

DESCRIPTION_OF_TREATMENT =\
        {'derive': 'Checkout and derive a new copy.',
         'checkout': 'Checkout to users workspace.',
        }

ROLE_MAPPING = {'creator': 'Author',
                'maintainer': 'Maintainer',
                'rightsHolder': 'Licensor',
                'editor': 'Editor',
                'translator': 'Translator',
               }


class IRhaptosWorkspaceSwordAdapter(ISWORDContentUploadAdapter):
    """ Marker interface for SWORD service specific to the Rhaptos 
        implementation.
    """


class IRhaptosEditMediaAdapter(ISWORDEMIRI):
    """ Marker interface for EM-IRI adapter specific to Rhaptos. """


def splitMultipartRequest(request):
    """ This is only to be used for multipart uploads. The first
        part is the atompub bit, the second part is the payload. """
    request.stdin.seek(0)
    message = message_from_file(request.stdin)
    atom, payload = message.get_payload()

    # Call get_payload with decode=True, so it can handle the transfer
    # encoding for us, if any.
    atom = atom.get_payload(decode=True)
    payload = payload.get_payload(decode=True)
    dom = parse(StringIO(atom))

    return dom, payload


def checkUploadSize(context, fp):
    """ Check size of file handle. """
    maxupload = getToolByName(context, 'sword_tool').getMaxUploadSize()
    fp.seek(0, 2)
    size = fp.tell()
    fp.seek(0)
    if size > maxupload:
        raise MaxUploadSizeExceeded("Maximum upload size exceeded",
            "The uploaded content is larger than the allowed %d bytes." % maxupload)


class RhaptosWorkspaceSwordAdapter(PloneFolderSwordAdapter):
    """ Rhaptos specific implement of the SWORD folder adapter.
    """
    adapts(IFolderish, IHTTPRequest)

    # keep a handle on what changed during the process
    description_of_changes = ''
    # keep a handle on the treatment of the object
    treatment = ''
    
    # the basic default encoding.
    # we change it to that set on the site a little later.
    encoding = None

    def getEncoding(self):
        """ if we have on return it,
            if not, figure out what it is, store it and return it.
        """
        if not self.encoding:
            self.encoding = getSiteEncoding(self.context)
        return self.encoding
    
    def generateFilename(self, name):
        """ Override this method to provide a more sensible name in the
            absence of content-disposition. """
        return self.context.generateUniqueId(type_name='Module')

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

            # Check upload size
            checkUploadSize(context, body)

            body.seek(0)
            dom = parse(body)
            body.seek(0)

            # Derive or checkout, if the headers are right
            obj = _deriveOrCheckout(dom)
            if obj is not None:
                return obj
        elif content_type.startswith('multipart/'):
            # Check upload size
            checkUploadSize(context, request.stdin)
            atom_dom, payload = splitMultipartRequest(request)
            obj = _deriveOrCheckout(atom_dom)
            if obj is not None:
                return obj

        checkUploadSize(context, request.stdin)
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
        forked_obj = obj.forkContent(license='', return_context=True)
        forked_obj.setState('created')
        forked_obj.setGoogleAnalyticsTrackingCode(None)

        # Delete temporary copy
        if to_delete_id:
            area.manage_delObjects(ids=[to_delete_id])
        return forked_obj


    def canCheckout(self, module):
        #return False
        pms = getToolByName(self.context, 'portal_membership')
        member = pms.getAuthenticatedMember()

        li = list(module.authors) \
            + list(module.maintainers) \
            + list(module.licensors) \
            + list(module.roles.get('translators', []))

        return member.getId() in li


    def checkoutModule(self, url):
        context = aq_inner(self.context)
        module_id = url.split('/')[-1]

        # Fetch module
        content_tool = getToolByName(self.context, 'content')
        module = content_tool.getRhaptosObject(module_id, 'latest')

        if not self.canCheckout(module):
            raise CheckoutUnauthorized(
                "You do not have permission to checkout %s" % module_id,
                "You are not a maintainer of the requested module or "
                "you do not have sufficient permissions for this workspace")

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


    def getModuleMetadata(self, obj, defaults_dict):
        metadata = {}
        for oerdc_name, cnx_name in METADATA_MAPPING.items():
            value = getattr(obj, cnx_name, defaults_dict.get(cnx_name, None))
            if value:
                metadata[cnx_name] = value
        return metadata


    def mergeMetadata(self, obj, fp):
        """        
            Merge the metadata on the obj (module) with whatever is in the fp
            parameter. From the spec. what should be replaced and what we should
            just add to.
            - title (dcterms:title) : Replace
            - abstract/summary (dcterms:abstract) : Replace
            - language (dcterms:language) : Replace
            - keyword (dcterms:subject) : Add
            - subject (dcterms:subject xsi:type="oerdc:Subjects") : Replace
            - contributor roles : Add
            - descriptionOfChanges : Replace
            - analyticsCode : Replace
            For more current info see: 
            - Google doc: SWORD V2 Spec for Publishing Modules in Connexions
        """        
        props = {}
        dom = parse(fp)
        # create a metadata dict that has all the values from obj, overridden
        # by the current dom values.
        metadata = self.getModuleMetadata(obj, {})
        metadata.update(self.getMetadata(dom, METADATA_MAPPING))
        for oerdc_name, cnx_name in METADATA_MAPPING.items():
            if cnx_name in ['keywords',]:
                old_value = getattr(obj, cnx_name)
                if old_value:
                    current_value = list(metadata.get(cnx_name, []))
                    current_value.extend(old_value)
                    metadata[cnx_name] = current_value
            # these ones we cannot pass on to the update_metadata script
            if cnx_name in ['description_of_changes', ]:
                props[cnx_name] = metadata.pop(cnx_name, '')
        props['treatment'] = self.treatment
        obj.manage_changeProperties(props)
        if metadata:
            obj.update_metadata(**metadata)
        self.addRoles(obj, dom)
        obj.reindexObject(idxs=metadata.keys())


    def updateMetadata(self, obj, dom):
        """ Metadata as described in:
            SWORD V2 Spec for Publishing Modules in Connexions
            Section: Metadata
        """
        props = {}
        metadata = {}
        metadata.update(self.getMetadata(dom, METADATA_MAPPING))
        for oerdc_name, cnx_name in METADATA_MAPPING.items():
            if cnx_name in ['keywords', 'subject',]:
                current_values = getattr(obj, cnx_name)
                if current_values:
                    if type(current_values) == TupleType:
                        current_values = list(current_values)
                    new_values = metadata.get(cnx_name, [])
                    if type(new_values) == StringType:
                        new_values = [new_values,]
                    for value in new_values:
                        if value not in current_values:
                            current_values.extend(value)
                    metadata[cnx_name] = new_values
            # these ones we cannot pass on to the update_metadata script
            if cnx_name in ['description_of_changes', ]:
                # if the object does not currently have a value for this field,
                # we must update it.
                if not getattr(obj, cnx_name, None):
                    props[cnx_name] = metadata.pop(cnx_name, '')
        props['treatment'] = self.treatment
        obj.manage_changeProperties(props)
        if metadata:
            obj.update_metadata(**metadata)
        self.addRoles(obj, dom)
        obj.reindexObject(idxs=metadata.keys())

    
    def replaceMetadata(self, obj, fp):
        """ We replace the module metadata with the values from the request.
            We use METADATA_DEFAULTS to reset those values we don't have
            on the request back to what they would be for a new module.
            This effictive 'clears' all metadata fields that were not supplied
            on the request.
            We delete all collaboration requests that are 'pending', but
            don't have equivalent data on the request.
            We add all new roles.
        """
        props = {}
        dom = parse(fp)
        # create a metadata dict that has all the defaults, overridden by the
        # current dom values. This way we will 'clear' the properties not in
        # the dom.
        metadata = copy(METADATA_DEFAULTS)
        metadata.update(self.getMetadata(dom, METADATA_MAPPING))
        for oerdc_name, cnx_name in METADATA_MAPPING.items():
            # these ones we cannot pass on to the update_metadata script
            if cnx_name in ['description_of_changes', ]:
                props[cnx_name] = metadata.pop(cnx_name, '')
        props['treatment'] = self.treatment
        obj.manage_changeProperties(props)
        if metadata:
            obj.update_metadata(**metadata)
        # we set GoogleAnalyticsTrackingCode explicitly, since the script
        # 'update_metadata' ignores empty strings.
        obj.GoogleAnalyticsTrackingCode = metadata.get('GoogleAnalyticsTrackingCode')
        # first delete all the pending collab request for which we have
        # no data in the request dom.
        self.deleteRoles(obj, dom)
        # now add any new roles
        self.addRoles(obj, dom)
        obj.reindexObject(idxs=metadata.keys())


    def updateContent(self, obj, fp, cksum, merge=False):
        kwargs = {
            'original_file_name': 'sword-import-file',
            'user_name': getSecurityManager().getUser().getUserName()
        }
        content = fp.read()

        # check the md5sum, if provided
        if cksum is not None:
            h = md5.md5(content).hexdigest()
            if h != cksum:
                raise ErrorChecksumMismatch("Checksum does not match",
                    "Calculated Checksum %s does not match %s" % (h, cksum))

        try:
            text, subobjs, meta = doTransform(obj, "sword_to_folder",
                content, meta=1, **kwargs)
        except (OOoImportError, BadZipfile), e:
            raise TransformFailed(str(e))

        if merge:
            if text:
                # Replace index.cnxml
                obj.manage_delObjects([obj.default_file,])
                obj.invokeFactory('CNXML Document', obj.default_file,
                    file=text, idprefix='zip-')
            makeContent(obj, subobjs)
        else:
            # Delete everything
            obj.manage_delObjects(obj.objectIds())
            if text:
                obj.invokeFactory('CNXML Document', obj.default_file,
                    file=text, idprefix='zip-')
            else:
                # Create an empty index.cnxml
                obj.invokeFactory('CNXML Document', obj.default_file,
                    idprefix='zip-')
            makeContent(obj, subobjs)

        # make sure that the cnxml is the latest version
        obj.getDefaultFile().upgrade()

    def updateObject(self, obj, filename, request, response, content_type):
        obj = obj.__of__(self.context)
        if content_type in ATOMPUB_CONTENT_TYPES:
            body = request.get('BODYFILE')
            body.seek(0)
            self.updateMetadata(obj, parse(body))
        elif content_type == 'application/zip':
            body = request.get('BODYFILE')
            cksum = request.get_header('Content-MD5')
            body.seek(0)
            self.updateContent(obj, body, cksum)
        elif content_type.startswith('multipart/'):
            cksum = request.get_header('Content-MD5')
            atom_dom, payload = splitMultipartRequest(request)
            self.updateMetadata(obj, atom_dom)
            self.updateContent(obj, StringIO(payload), cksum)

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
        encoding = self.getEncoding()
        headers = []
        for prefix, uri in dom.documentElement.attributes.items():
            for name in mappings.keys():
                values = []
                for node in dom.getElementsByTagNameNS(uri, name):
                    content = ""
                    # get the xml of all child nodes since some tags
                    # may contain markup, eg abstract may contain CNXML
                    for child in node.childNodes:
                        content += child.toxml().encode(encoding)
                    if content:
                        values.append(content)
                if values:
                    headers.append((mappings[name], '\n'.join(values)))

        return headers
   

    def _getNewRoles(self, dom):
        encoding = self.getEncoding()
        newRoles = {}
        for atom_role, cnx_role in ROLE_MAPPING.items():
            for namespace in [DCTERMS_NAMESPACE, OERDC_NAMESPACE]:
                for element in dom.getElementsByTagNameNS(namespace, atom_role):
                    ids = newRoles.get(cnx_role, [])
                    userid = element.getAttribute('oerdc:id')
                    if userid:
                        ids.append(userid.encode(encoding))
                        newRoles[cnx_role] = ids
        return newRoles


    def deleteRoles(self, obj, dom):
        """ Compare the roles in the dom to all the pending collab requests on obj.
            Delete the pending collabs not listed in the dom.
        """
        pending_collaborations = obj.getPendingCollaborations()
        roles = self._getNewRoles(dom)
        for user_id, collab_request in pending_collaborations.items():
            if user_id not in roles.keys() and user_id != obj.Creator():
                obj.reverseCollaborationRequest(collab_request.id)
        

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
        self.description_of_changes = DESCRIPTION_OF_CHANGES[action]
        self.treatment = DESCRIPTION_OF_TREATMENT[action]
        return obj


class RhaptosEditMedia(EditMedia):
    def GET(self):
        return self.context.module_export(format='zip')
        

    def PUT(self):
        """ PUT against an existing item should update it.
        """
        # Check upload size
        body = self.request.get('BODYFILE')
        checkUploadSize(self.context, body)

        filename = self.request.get_header(
            'Content-Disposition', self.context.title)
        content_type = self.request.get_header('Content-Type')

        parent = self.context.aq_inner.aq_parent
        adapter = getMultiAdapter(
            (parent, self.request), IRhaptosWorkspaceSwordAdapter)

        cksum = self.request.get_header('Content-MD5')
        merge = self.request.get_header('Update-Semantics')

        body.seek(0)
        adapter.updateContent(self.context, body, cksum,
            merge is not None and merge.lower()=='merge')

    def addFile(self, context, filename, f):
        # These files may never be uploaded, because we cannot process
        # them here, the spec says no.
        if filename == 'index.cnxml':
            raise OverwriteNotPermitted(
                "Overwriting index.cnxml is not allowed")

        # Word processor documents are not allowed
        wordext = [x for x in ('odt','sxw','docx','rtf','doc') \
            if filename.endswith('.' + x)]
        if wordext:
            # Its a word processor file, reject it
            raise OverwriteNotPermitted(
                "Overwriting files of type %s is not allowed" % wordext[0])

        filename = normalizeFilename(filename)

        # If there is another file by the same name, protest
        if filename in context.objectIds():
            raise OverwriteNotPermitted(
                "An object named %s already exists" % filename)

        # Finally, upload as a unified file
        context.invokeFactory('UnifiedFile', filename, file=f)
        obj = context._getOb(filename)
        obj.setTitle(filename)
        obj.reindexObject(idxs='Title')
        return obj

    @show_error_document
    def POST(self):
        """ This implements POST functionality on the EM-IRI. A POST always
            adds content, and in this case it is not allowed to overwrite.
            Within the rhaptos context it is also not allowed to use any
            of the usual transforms, and files that would normally be
            converted to other formats, such as OOo or MS Word, will be
            left as is. """
        context = aq_inner(self.context)
        if self.request.get_header('Content-Type').lower().startswith(
            'application/zip') or self.request.get_header(
            'Packaging', '').endswith('/SimpleZip'):
            # Unpack the zip and add the various items
            try:
                zipfile = ZipFile(self.request['BODYFILE'], 'r')
            except BadZipfile:
                raise BadRequest("Invalid zip file")

            namelist = zipfile.namelist()
            lenlist = len(namelist)

            # Empty zip file?
            if lenlist == 0:
                raise BadRequest("Zip file is empty")

            if lenlist > 1:
                prefix = os.path.commonprefix(namelist)
            else:
                prefix = os.path.dirname(namelist[0]) + '/'
            namelist = [name[len(prefix):] for name in namelist]

            for f in namelist:
                if not f:
                    continue # Directory name in the listing
                if f.find('/')!=-1:
                    continue  # Subdirectories ignored
                # When this moves to python2.6, please use zipfile.open here
                unzipfile = StringIO(zipfile.read(prefix + f))
                self.addFile(context, f, unzipfile)

            # Returned Location header points to the EM-IRI for zipfile upload
            self.request.response.setHeader('Location', '%s/editmedia' % context.absolute_url())
            self.request.response.setStatus(201)
            return ''
        else:
            # Rhaptos uses UnifiedFile for everything, so we will not use
            # content_type_registry here. First get the file name. The client
            # MUST supply this
            disposition = self.request.get_header('Content-Disposition')
            if disposition is None:
                raise BadRequest("The request has no Content-Disposition")
            try:
                filename = [x.strip() for x in disposition.split(';') \
                    if x.strip().startswith('filename=')][0][9:]
            except IndexError:
                raise BadRequest(
                    "The Content-Disposition header has no filename")

            obj = self.addFile(context, filename, self.request['BODYFILE'])

            # Returned Location header must point directly at the file
            self.request.response.setHeader('Location', obj.absolute_url())
            self.request.response.setStatus(201)
            return ''

    def DELETE(self):
        """ Delete the contained items of a collection.
            The reset the required fields to the Rhaptos defaults.
        """
        returnValue = EditMedia.DELETE(self)
        self.context.createTemplate()
        return returnValue
