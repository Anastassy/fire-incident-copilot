from mcp.server.fastmcp import FastMCP

# Owner: Agent C. Register tools here, thin wrappers over app/services/*:
#   list_devices, get_device, query_telemetry, get_latest_readings,
#   list_incidents, get_incident, create_incident, update_incident, link_evidence,
#   list_dashboards, get_dashboard, create_dashboard, update_dashboard
# Expose via streamable-http/SSE transport so it can be mounted or run standalone.
mcp = FastMCP("safety-platform")
