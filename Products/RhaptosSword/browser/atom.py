from Products.Five import BrowserView
from Products.CNXMLTransforms.helpers import OOoImportError, doTransform, makeContent
from Products.RhaptosWorkgroup.interfaces import IWorkgroup
from zipfile import BadZipfile
from zope.interface import classImplements
import transaction
from AccessControl import getSecurityManager, Unauthorized
from Products.CMFPlone import PloneFolder


# Patch Member private folders to accept AtomPub pushes
#classImplements(PloneFolder, IWorkgroup)

class AtomView(BrowserView):

  def addModule(self, **kwargs):
    method = self.request['REQUEST_METHOD']
    if method == "GET":
      self.request.RESPONSE.write("LAKJSDHFKJHF") 
    elif method == "POST":
        # zipped word doc is part of the request
        # state.setStatus('ContentCreation')
        # If this folder allows Modules to be created, use it. Otherwise, use
        # the user's home folder. Could be extended in the future to a user
        # configurable workgroup
        
        context = self.context
        response = self.request.RESPONSE
        #state = self.state
        
        
        type_name = 'Module'
        typeinfo = context.getTypeInfo()
        cntxt = context

        context.plone_log("SWORD Import: Creating module in %s ." %cntxt)
        id=cntxt.generateUniqueId(type_name)
        try:
            new_id = cntxt.invokeFactory(id=id, type_name=type_name)
        except Unauthorized, e:
            context.plone_log("SWORD Import: Aborted. Not authorized for location and sending custom Unauthorized response.")
            response.setStatus('Unauthorized')
            #state.setStatus('SwordAnonymousPost')
            return None#state.set(context=context)

        if new_id is None or new_id == '':
           new_id = id
        rme=getattr(cntxt, new_id, None)
        if rme is not None: context.plone_log("SWORD Import: Created module id=%s ." % (new_id))

        rme.editModule(self, kwargs)


  def editModule(self, **kwargs):

        rme = self.context
        context = self.context
        response = self.request.RESPONSE
        # Perform the import
        try:
            payload = context.REQUEST['BODY']
            if payload:
              kwargs = {'original_file_name':'sword-import-file', 'user_name':getSecurityManager().getUser().getUserName()}
              text, subobjs, meta = doTransform(rme, "sword_to_folder", payload, meta=1, **kwargs)
#              context.plone_log("SWORD Import with id=%s: Transformed metadata and transformed document to cnxml." % (new_id))
              if text:
                rme.manage_delObjects([rme.default_file,])

                rme.invokeFactory('CNXML Document', rme.default_file, file=text, idprefix='zip-')
              makeContent(rme, subobjs)

              # Parse the returned mdml and set attributes up on the ModuleEditor object
              # Add any additional, unmatched, aka uncredited authors
              props = meta['properties']
              rme.updateProperties(props)
              # Make sure the metadata gets into the cnxml
              rme.editMetadata()

#            context.plone_log("SWORD Import with id=%s: Completed." % (new_id))
            response.setStatus('Created')
            return None#state.set(status='SwordImportSuccess', context=rme)

        except OOoImportError, e:
            transaction.abort()
#            context.plone_log("SWORD Import with id=%s: Aborted. There were problems transforming the openoffice or word document." % (new_id))
            message = context.translate("message_could_not_import", {"errormsg":e}, domain="rhaptos",
                                        default="Could not import file. %s" % e)
            response.setStatus('BadRequest')
            return None#state.set(status='SwordImportError', portal_status_message=message)
        except BadZipfile, e:
            transaction.abort()
#            context.plone_log("SWORD Import with id=%s: Aborted. There were problems with the uploaded zip file." % (new_id))
            response.setStatus('BadRequest')
            #state.setStatus('SwordErrorZip')
            return None#state.set(context=context)

