## json.cpy : Provide a JSON version of module cnxml

request = context.REQUEST
response = context.REQUEST.RESPONSE 
tool = context.sword_tool

content = context.getDefaultFile().getSource()

response.setHeader('Content-Type', 'application/json')
data = tool.cnxml2json(content)
return data
