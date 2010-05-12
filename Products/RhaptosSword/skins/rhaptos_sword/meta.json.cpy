## meta.json.cpy : Provide a JSON version of module metadata

request = context.REQUEST
response = context.REQUEST.RESPONSE 
tool = context.sword_tool

content = context.getDefaultFile().getSource()

response.setHeader('Content-Type', 'application/json')

data = tool.mdml2json(content)
return data
