## atom.cpy : process sword requests
##parameters=

request = context.REQUEST
sword_tool = context.sword_tool

acceptingSwordRequests = sword_tool.acceptingSwordRequests

member = context.portal_membership.getAuthenticatedMember()
isAnonymousUser = ( str(member) == 'Anonymous User' )

method = request['REQUEST_METHOD']

context.plone_log("hi mom.  send more money.")
context.plone_log("method is %s." % method)

if method == "GET":
    # service request
    state.setStatus('ServiceDiscovery')
    return state.set(context=context)
elif method == "POST":
    # content post
    if not acceptingSwordRequests:
        # return 404?
        pass
    elif isAnonymousUser:
        # return 404
        pass
    else:
        # zipped word doc is part of the request
        # state.setStatus('ContentCreation')
        pass




