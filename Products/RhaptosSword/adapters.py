from copy import copy
from xml.dom.minidom import parse
from zipfile import BadZipfile
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

from Products.PloneLanguageTool import availablelanguages as lang_tool
from Products.CMFCore.utils import getToolByName
from Products.CMFCore.interfaces import IFolderish

from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from Products.CNXMLTransforms.helpers import CNXImportError, doTransform, makeContent
from Products.CNXMLDocument.XMLService import XMLParserError
from Products.CNXMLDocument.XMLService import validate

from rhaptos.atompub.plone.exceptions import PreconditionFailed
from rhaptos.atompub.plone.browser.atompub import ATOMPUB_CONTENT_TYPES
from rhaptos.swordservice.plone.browser.sword import PloneFolderSwordAdapter
from rhaptos.swordservice.plone.browser.sword import EditMedia
from rhaptos.swordservice.plone.browser.sword import ISWORDContentUploadAdapter 
from rhaptos.swordservice.plone.browser.sword import show_error_document
from rhaptos.swordservice.plone.interfaces import ISWORDEMIRI
from rhaptos.swordservice.plone.exceptions import ErrorChecksumMismatch
from rhaptos.swordservice.plone.exceptions import BadRequest

from Products.RhaptosSword.normalize import normalizeFilename
from Products.RhaptosSword.interfaces import ICollabRequest
from Products.RhaptosSword.exceptions import CheckoutUnauthorized
from Products.RhaptosSword.exceptions import OverwriteNotPermitted
from Products.RhaptosSword.exceptions import TransformFailed
from Products.RhaptosSword.exceptions import DepositFailed

from utils import splitMultipartRequest, checkUploadSize

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

ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"

# in order of precedence
METADATA_NAMESPACES = (OERDC_NAMESPACE, DCTERMS_NAMESPACE, ATOM_NAMESPACE)

METADATA_MAPPING =\
        {'title': 'title',
         'abstract': 'abstract',
         'language': 'language',
         'subject': 'keywords',
         'oer-subject': 'subject',
         'descriptionOfChanges': 'message',
         'analyticsCode': 'GoogleAnalyticsTrackingCode',
        }

METADATA_DEFAULTS = \
        {'title': '(Untitled)',
         'abstract': '',
         'language': 'en',
         'keywords': [],
         'subject': [],
         'GoogleAnalyticsTrackingCode': '',
        }

DESCRIPTION_OF_TREATMENT =\
        {'derive': "Checkout and derive a new copy.",
         'checkout': "Checkout to user's workspace.",
         'create': "Created a module.",
         'save': "Changes saved."
        }

ROLE_MAPPING = {'creator': 'Author',
                'maintainer': 'Maintainer',
                'rightsHolder': 'Licensor',
                'editor': 'Editor',
                'translator': 'Translator',
               }

DEFAULT_ROLES = ['Author', 'Maintainer', 'Licensor']

class IRhaptosWorkspaceSwordAdapter(ISWORDContentUploadAdapter):
    """ Marker interface for SWORD service specific to the Rhaptos 
        implementation.
    """


class IRhaptosEditMediaAdapter(ISWORDEMIRI):
    """ Marker interface for EM-IRI adapter specific to Rhaptos. """


class RhaptosWorkspaceSwordAdapter(PloneFolderSwordAdapter):
    """ Rhaptos specific implement of the SWORD folder adapter.
    """
    adapts(IFolderish, IHTTPRequest)
    
    # the action currently being taken
    action = None
    
    # help us remember what metadata semantics were chosen
    update_semantics = 'created'
    
    # the basic default encoding.
    # we change it to that set on the site a little later.
    encoding = 'utf-8'


    def __init__(self, context, request):
        super(RhaptosWorkspaceSwordAdapter, self).__init__(context, request)
        self.encoding = getSiteEncoding(self.context)
        self.pmt = getToolByName(self.context, 'portal_membership')

    def generateFilename(self, name):
        """ Override this method to provide a more sensible name in the
            absence of content-disposition. """
        return self.context.generateUniqueId(type_name='Module')

    def createObject(self, context, name, content_type, request):
        # see if the request has a atompub payload that specifies,
        # module id in "source" or "mdml:derived_from" in ATOM entry.
        def _deriveOrCheckout(dom):
            # Check if this is a request to derive or checkout an item
            # 'item' could be a module or a collection at this point.
            elements = dom.getElementsByTagNameNS(
                "http://purl.org/dc/terms/", 'isVersionOf')
            if len(elements) > 0:
                item_id = \
                    elements[0].firstChild.toxml().encode(self.encoding)
                obj = self.checkoutItem(item_id)
                self.action = 'checkout'
                return obj
            elements = dom.getElementsByTagNameNS(
                "http://purl.org/dc/terms/", 'source')
            if len(elements) > 0:
                # now we can fork / derive the module
                item_id = \
                    elements[0].firstChild.toxml().encode(self.encoding)
                obj = self.deriveItem(item_id)
                self.action = 'derive'
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
            atom_dom, payload, payload_type = splitMultipartRequest(request)
            obj = _deriveOrCheckout(atom_dom)
            if obj is not None:
                return obj

        checkUploadSize(context, request.stdin)
        # if none of the above is the case we let the ancestor to its thing
        # we set the action to 'create' since there is no more info to work
        # with.
        obj = super(RhaptosWorkspaceSwordAdapter, self).createObject(
            context, name, content_type, request)
        self.action = 'create'
        return obj


    def deriveItem(self, url):
        """ We checkout the object, fork it, remove the temp one and 
            return the forked copy.
        """
        item_id = url.split('/')[-1]
        # Fetch item and area
        version = 'latest' #TODO: honour the version in the xml payload
        content_tool = getToolByName(self.context, 'content')
        item = content_tool.getRhaptosObject(item_id, version)
        area = self.context
        # We create a copy that we want to clean up later, let's track the id
        to_delete_id = area.generateUniqueId()
        area.invokeFactory(id=to_delete_id, type_name=item.portal_type)
        obj = area._getOb(to_delete_id)

        # item must be checked out to area before a fork is possible
        obj.setState('published')
        obj.checkout(item.objectId)

        # Do the fork
        forked_obj = obj.forkContent(license='', return_context=True)
        forked_obj.setState('created')
        forked_obj.setGoogleAnalyticsTrackingCode(None)

        # remove all roles except those of the author
        forked_obj.resetOptionalRoles()
        # should not be necessary...
        forked_obj.deleteCollaborationRequests()
        owner_id = forked_obj.Creator()
        for user_id in forked_obj.getCollaborators():
            if user_id != owner_id:
                forked_obj.removeCollaborator(user_id)

        # Delete temporary copy
        if to_delete_id:
            area.manage_delObjects(ids=[to_delete_id])
        return forked_obj


    def canCheckout(self, item):
        #return False
        pms = getToolByName(self.context, 'portal_membership')
        member = pms.getAuthenticatedMember()

        li = list(item.authors) \
            + list(item.maintainers) \
            + list(item.licensors) \
            + list(item.roles.get('translators', []))

        return member.getId() in li


    def checkoutItem(self, url):
        context = aq_inner(self.context)
        item_id = url.split('/')[-1]

        # Fetch item
        content_tool = getToolByName(self.context, 'content')
        item = content_tool.getRhaptosObject(item_id, 'latest')

        if not self.canCheckout(item):
            raise CheckoutUnauthorized(
                "You do not have permission to checkout %s" % item_id,
                "You are not a maintainer of the requested item or "
                "you do not have sufficient permissions for this workspace")

        if item_id not in context.objectIds():
            context.invokeFactory(id=item_id, type_name=item.portal_type)
            obj = context._getOb(item_id)
            obj.setState('published')
            obj.checkout(item.objectId)
            return obj
        else:
            obj = context._getOb(item_id)
            if obj.state == 'published':
                # Check out on top of published copy
                obj.checkout(item.objectId)
                return obj
            elif obj.state == "checkedout" and obj.version == item.version:
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


    def mergeMetadata(self, obj, dom):
        """        
            Merge the metadata on the obj (module) with whatever is in the dom
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
        self.update_semantics = 'merge'
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
        if metadata:
            self.validate_metadata(metadata)
            obj.update_metadata(**metadata)
        self.updateRoles(obj, dom)
        obj.reindexObject(idxs=metadata.keys())


    def updateMetadata(self, obj, dom):
        """ Metadata as described in:
            SWORD V2 Spec for Publishing Modules in Connexions
            Section: Metadata
        """
        self.update_semantics = 'merge'
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
        if metadata:
            self.validate_metadata(metadata)
            obj.update_metadata(**metadata)
        self.updateRoles(obj, dom)
        obj.reindexObject(idxs=metadata.keys())

    
    def replaceMetadata(self, obj, dom):
        """ We replace the module metadata with the values from the request.
            We use METADATA_DEFAULTS to reset those values we don't have
            on the request back to what they would be for a new module.
            This effictive 'clears' all metadata fields that were not supplied
            on the request.
            We delete all collaboration requests that are 'pending', but
            don't have equivalent data on the request.
            We add all new roles.
            TODO: Checkout the _reset method in ModuleEditor. It might be
                  better to use that than do our own thing here.
        """
        self.update_semantics = 'replace'
        # create a metadata dict that has all the defaults, overridden by the
        # current dom values. This way we will 'clear' the properties not in
        # the dom.
        metadata = copy(METADATA_DEFAULTS)
        metadata.update(self.getMetadata(dom, METADATA_MAPPING))
        if metadata:
            self.validate_metadata(metadata)
            obj.update_metadata(**metadata)
        # we set GoogleAnalyticsTrackingCode explicitly, since the script
        # 'update_metadata' ignores empty strings.
        obj.GoogleAnalyticsTrackingCode = metadata.get('GoogleAnalyticsTrackingCode')
        self.updateRoles(obj, dom)
        obj.reindexObject(idxs=metadata.keys())

    def validate_metadata(self, metadata):
        trackingcode = metadata.get('GoogleAnalyticsTrackingCode')
        if trackingcode:
            parts = trackingcode.split('-')
            valid = len(parts) == 3 and \
                    parts[0] == 'UA' and \
                    parts[1].isdigit() and \
                    parts[2].isdigit()
            if not valid:
                raise ValidationError(
                    "Invalid Google Analytics Tracking Code: %s" % trackingcode)

        abstract = metadata.get('abstract')
        if abstract:
            # validate CNXML pieces
            wrappedabstract = """\
<md:abstract
    xmlns="http://cnx.rice.edu/cnxml"
    xmlns:bib="http://bibtexml.sf.net/"
    xmlns:m="http://www.w3.org/1998/Math/MathML"
    xmlns:md="http://cnx.rice.edu/mdml"
    xmlns:q="http://cnx.rice.edu/qml/1.0">%s</md:abstract>""" % abstract
            results = validate(wrappedabstract, "http://cnx.rice.edu/technology/cnxml/schema/rng/0.7/cnxml-fragment.rng")
            if results:
                error = ""
                for line, msg in results:
                    error += "line %s: %s\n" % (line, msg)
                raise ValidationError(
                    "Invalid abstract:\n%s" % error)
        
        # validate language
        lang = metadata.get('language', None)
        if lang:
            lang_codes = lang_tool.languages.keys() + lang_tool.combined.keys()
            if lang not in lang_codes:
                raise ValidationError('The language %s is not valid.' % value)

        # validate subject
        mdt = getToolByName(self.context, 'portal_moduledb')
        subjects = mdt.sqlGetTags(scheme='ISKME subject').tuples()
        subjects = [tup[1].lower() for tup in subjects]
        for subject in metadata.get('subject', []):
            if subject.lower() not in subjects:
                raise ValidationError(
                    'The subject %s is invalid.' % subject)

    def updateContent(self, obj, fp, content_type, cksum, merge=False):
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

        transform = "sword_to_folder"
        if content_type.lower().startswith("application/msword"):
            transform = "oo_to_cnxml"

        try:
            text, subobjs, meta = doTransform(obj, transform,
                content, meta=1, **kwargs)
        except (CNXImportError, BadZipfile), e:
            raise TransformFailed(str(e))
        except XMLParserError, e:
            raise DepositFailed(str(e))

        # Set by mets.xml inside ZIP
        if meta.has_key('propertіes'):
            props = meta['properties']
            obj.updateProperties(props)
            # Make sure the metadata gets into the cnxml
            obj.editMetadata()
        elif meta.has_key('featured_links'):
            # first we clean out all the old links
            obj.setLinks([])
            # now we add the ones specified in the cnxml
            for link in meta.get('featured_links'):
                obj.doAddLink(link)
        if merge:
            if text:
                # Replace index.cnxml
                obj.manage_delObjects([obj.default_file,])
                obj.invokeFactory('CNXML Document', obj.default_file,
                    file=text, idprefix='zip-')
            makeContent(obj, subobjs)
        else:
            # Delete everything, but preserve collaboration requests
            obj.manage_delObjects(
                [x.getId() for x in obj.objectValues() \
                    if not ICollabRequest.providedBy(x)])
            if text:
                obj.invokeFactory('CNXML Document', obj.default_file,
                    file=text, idprefix='zip-')
            else:
                # Create an empty index.cnxml
                obj.createTemplate()

            makeContent(obj, subobjs)

        # make sure that the cnxml is the latest version
        obj.getDefaultFile().upgrade()

        # After updating the content, set status to modified, reindex
        if self.action not in ('create', 'derive', 'checkout'):
            self.action = 'save'


    def updateObject(self, obj, filename, request, response, content_type):
        obj = obj.__of__(self.context)
        if content_type in ATOMPUB_CONTENT_TYPES:
            body = request.get('BODYFILE')
            body.seek(0)
            if self.action in ['derive', 'checkout']:
                self.mergeMetadata(obj, parse(body))
            else:
                self.updateMetadata(obj, parse(body))
        elif content_type == 'application/zip':
            body = request.get('BODYFILE')
            cksum = request.get_header('Content-MD5')
            body.seek(0)
            self.updateContent(obj, body, content_type, cksum)
        elif content_type.startswith('multipart/'):
            cksum = request.get_header('Content-MD5')
            atom_dom, payload, payload_type = splitMultipartRequest(request)
            self.updateMetadata(obj, atom_dom)
            self.updateContent(obj, StringIO(payload), payload_type, cksum)

        # blank the message on derive or checkout - see ticket 11879
        if self.action in ('derive', 'checkout'):
            obj.logAction(self.action, '')
        else:
            obj.logAction(self.action, obj.message)
        return obj


    def getMetadata(self, dom, mapping):
        """ Get metadata from DOM
        """
        metadata = {}
        for ns in METADATA_NAMESPACES:
            for metaname, cnxname in mapping.items():
                value = []
                for node in dom.getElementsByTagNameNS(ns, metaname):
                    content = ""
                    # get the xml of all child nodes since some tags
                    # may contain markup, eg abstract may contain CNXML
                    for child in node.childNodes:
                        content += child.toxml().encode(self.encoding)
                    if content:
                        if node.getAttribute('xsi:type') == 'oerdc:Subject':
                            metadata.setdefault('subject', [])
                            metadata['subject'].append(content)
                        else:
                            value.append(content)

                # format values
                if cnxname not in ('keywords', 'subject'):
                    # there can be only one!
                    if len(value) > 1:
                        raise ValidationError('More than one %s.' %metaname)
                    # pick the last value in the atom entry for string
                    # properties
                    value = value and value[-1] or ''

                if value and not metadata.has_key(cnxname):
                    metadata[cnxname] = value
        return metadata


    def getRolesFromDOM(self, dom):
        domRoles = {}
        for atom_role, cnx_role in ROLE_MAPPING.items():
            for namespace in [DCTERMS_NAMESPACE, OERDC_NAMESPACE]:
                for element in dom.getElementsByTagNameNS(namespace, atom_role):
                    ids = domRoles.get(cnx_role, [])
                    userid = element.getAttribute('oerdc:id')
                    userid = userid.encode(self.encoding)
                    if userid not in ids:
                        ids.append(userid)
                        domRoles[cnx_role] = ids
        return domRoles


    def getRolesFromModule(self, module):
        moduleRoles = {}
        for cnx_role in ROLE_MAPPING.values():
            role_name = cnx_role.lower() + 's'
            ids = getattr(module, role_name, [])
            roles = moduleRoles.get(cnx_role, [])
            roles.extend(ids)
            moduleRoles[cnx_role] = roles
        moduleRoles.update(module.getRolesDict())
        return moduleRoles


    def validateRoles(self, roles):
        for role, user_ids in roles.items():
            for u_id in user_ids:
                if not self.userExists(u_id):
                    raise ValidationError('The user (%s) does not exist.' %u_id)
        return roles

    
    def userExists(self, userid):
        if userid is None: return False
        return self.pmt.getMemberById(userid)


    def getDefaultRoles(self, user_id):
        defaultRoles = {}
        for role in DEFAULT_ROLES:
            defaultRoles[role] = [user_id]
        return defaultRoles


    def updateRoles(self, obj, dom):
        """
        Compute the updated roles
        - just the list of userids and roles in the xml
        Compute the deleted roles
        - collaborators that are currently on the object, but not in the xml
        Compute the cancelled roles
        - pending collaboration request for which there are no roles in the xml
        """
        domRoles = self.validateRoles(self.getRolesFromDOM(dom))
        moduleRoles = self.validateRoles(self.getRolesFromModule(obj))

        updateRoles = {}
        deleteUsers = []
        cancelRoles = []
        
        if self.action == 'create' or self.update_semantics == 'replace':
            # set default roles only if the dom contains no roles
            if len(domRoles.keys()) == 0:
                updateRoles = self.getDefaultRoles(
                    self.pmt.getAuthenticatedMember().getId())
            else:
                updateRoles.update(domRoles)

        elif self.update_semantics == 'merge':
            updateRoles.update(moduleRoles)
            for role, userids in domRoles.items():
                userids = set(userids)
                userids.union(updateRoles.get(role, []))
                updateRoles[role] = list(userids)

        elif self.update_semantics == 'replace':
            currentUsers = set()
            for userids in moduleRoles.values():
                currentUsers.update(userids)
            domUsers = set()
            for userids in domRoles.values():
                domUsers.update(userids)
            for userids in updateRoles.values():
                domUsers.update(userids)
            deleteUsers = currentUsers.difference(domUsers)

            # XXX: Workaround for bug in generateCollaborationRequests that
            # requires a user listed in deleteRoles to be present in
            # newRoles
            for role, userids in moduleRoles.items():
                for user in deleteUsers:
                    if user in userids:
                        updateRoles.setdefault(role, [])
                        updateRoles[role].append(user)

        self._updateRoles(obj, updateRoles, deleteUsers, cancelRoles)
    
    
    def _updateRoles(self, obj, updateRoles={}, deleteRoles=[], cancelRoles=[]):
        """ Basic copy of RhaptosModuleEditor skins script update_roles.
        """
        #user_role_delta = {}
        pending = obj.getPendingCollaborations()

        collabs = obj.getCollaborators()

        user_role_delta = obj.generateCollaborationRequests(
            newUser=False, newRoles=updateRoles, deleteRoles=deleteRoles)
                
        for p in user_role_delta.keys():
            if p in pending.keys():
                new_changes = pending[p].roles.copy()
                for role in user_role_delta[p]:
                    delta = user_role_delta[p][role]
                    if role in new_changes:
                        if new_changes[role] != delta:
                            new_changes.pop(role)
                        elif new_changes[role] == delta:
                            #Shouldn't happen
                            pass
                    else:
                        new_changes[role] = delta
                if not new_changes:
                    obj.manage_delObjects(pending[p].id)
                else:
                    obj.editCollaborationRequest(pending[p].id, new_changes)
            else:
                obj.addCollaborator(p)
                obj.requestCollaboration(p, user_role_delta[p])

        for u in cancelRoles:
            if u in obj.getPendingCollaborations():
                # Revert the new roles back to the published version
                obj.reverseCollaborationRequest(pending[u].id)
                # Delete the collaboration request
                obj.manage_delObjects(pending[u].id)

        #Get the collaborators again if they have changed
        all_roles = {}
        for rolename in obj.default_roles + getattr(obj, 'optional_roles', {}).keys():
            for r in getattr(obj,rolename.lower()+'s',[]):
                all_roles[r]=None
            for r in getattr(obj, 'pub_'+rolename.lower()+'s', []):
                all_roles[r]=None
            
        collabs = obj.getCollaborators()
        for c in collabs:
            if c not in all_roles.keys():
                obj.removeCollaborator(c)

    
class RhaptosEditMedia(EditMedia):

    def __init__(self, context, request):
        """ we override init in order to add DELETE as a legitemate
            call in RhaptosSword land.
        """
        EditMedia.__init__(self, context, request)
        self.callmap.update({'DELETE': self.DELETE,})

    def GET(self):
        # If the module is published, do a transparent checkout
        if self.context.state == 'published':
            self.context.checkout(self.context.objectId)
        return self.context.module_export(format='zip')
        

    @show_error_document
    def PUT(self):
        """ PUT against an existing item should update it.
        """
        # Check upload size
        body = self.request.get('BODYFILE')
        checkUploadSize(self.context, body)

        # If the module is published, do a transparent checkout
        if self.context.state == 'published':
            self.context.checkout(self.context.objectId)

        filename = self.request.get_header(
            'Content-Disposition', self.context.title)
        content_type = self.request.get_header('Content-Type')

        parent = self.context.aq_inner.aq_parent
        adapter = getMultiAdapter(
            (parent, self.request), IRhaptosWorkspaceSwordAdapter)

        cksum = self.request.get_header('Content-MD5')
        merge = self.request.get_header('Update-Semantics')

        body.seek(0)
        adapter.updateContent(self.context, body, content_type, cksum,
            merge == 'http://purl.org/oerpub/semantics/Merge')
        self.context.logAction(adapter.action)

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

        # If the module is published, do a transparent checkout
        if context.state == 'published':
            context.checkout(context.objectId)

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
        ids = self.context.objectIds()
        self.context.manage_delObjects(ids)
        self.context.createTemplate()
        return self.request.response.setStatus(200)
