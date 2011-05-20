from Products.Five import BrowserView

class AtomView(BrowserView):

  def replaceModule(self, **kwargs):
    method = request['REQUEST_METHOD']
    if method == "GET":
      self.request.RESPONSE.write("LAKJSDHFKJHF") 
    elif method == "POST":
        # zipped word doc is part of the request
        # state.setStatus('ContentCreation')
        # If this folder allows Modules to be created, use it. Otherwise, use
        # the user's home folder. Could be extended in the future to a user
        # configurable workgroup
        
        context = self.context
        response = self.response
        state = self.state
        
        
        type_name = 'Module'
        typeinfo = context.getTypeInfo()
        cntxt = context

        context.plone_log("SWORD Import for %s: Creating module in %s ." % (memberId, cntxt))
        id=cntxt.generateUniqueId(type_name)
        try:
            new_id = cntxt.invokeFactory(id=id, type_name=type_name)
        except Unauthorized, e:
            context.plone_log("SWORD Import for %s: Aborted. Not authorized for location and sending custom Unauthorized response." % memberId)
            response.setStatus('Unauthorized')
            state.setStatus('SwordAnonymousPost')
            return state.set(context=context)

        if new_id is None or new_id == '':
           new_id = id
        rme=getattr(cntxt, new_id, None)
        if rme is not None: context.plone_log("SWORD Import for %s: Created module id=%s ." % (memberId, new_id))

        # Perform the import
        try:
            payload = context.REQUEST['BODY']
            if payload:
              kwargs = {'original_file_name':'sword-import-file', 'user_name':getSecurityManager().getUser().getUserName()}
              text, subobjs, meta = doTransform(rme, "sword_to_folder", payload, meta=1, **kwargs)
              context.plone_log("SWORD Import for %s with id=%s: Transformed metadata and transformed document to cnxml." % (memberId, new_id))
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

            context.plone_log("SWORD Import for %s with id=%s: Completed." % (memberId, new_id))
            response.setStatus('Created')
            return state.set(status='SwordImportSuccess', context=rme)

        except OOoImportError, e:
            transaction.abort()
            context.plone_log("SWORD Import for %s with id=%s: Aborted. There were problems transforming the openoffice or word document." % (memberId, new_id))
            message = context.translate("message_could_not_import", {"errormsg":e}, domain="rhaptos",
                                        default="Could not import file. %s" % e)
            response.setStatus('BadRequest')
            return state.set(status='SwordImportError', portal_status_message=message)
        except BadZipfile, e:
            transaction.abort()
            context.plone_log("SWORD Import for %s with id=%s: Aborted. There were problems with the uploaded zip file." % (memberId, new_id))
            response.setStatus('BadRequest')
            state.setStatus('SwordErrorZip')
            return state.set(context=context)

    pass
