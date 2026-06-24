import { taskGraphEdgeRelationRegistrations } from "./taskGraphEdgeRelationRegistry";
import { allGraphFileRoles } from "./taskGraphFileRoleRegistry";
import { defaultWorkspaceExtensions, allGraphWorkspaceExtensions } from "./taskGraphInstanceWorkspaceRegistry";
import { taskGraphNodeRegistrations } from "./taskGraphNodeRegistry";
import { listGraphTemplates } from "./taskGraphTemplateRegistry";
import { conversationPortRegistrations } from "./taskGraphConversationPortRegistry";
import { defaultAgentWorldRegistrations, defaultResourceWorldRegistrations } from "./taskGraphWorldRegistries";

export function buildTaskGraphRegistrySnapshot() {
  return {
    nodes: taskGraphNodeRegistrations,
    edges: taskGraphEdgeRelationRegistrations,
    templates: listGraphTemplates(),
    fileRoles: allGraphFileRoles(),
    workspaceExtensions: allGraphWorkspaceExtensions(),
    defaultWorkspaceExtensions,
    agentWorld: defaultAgentWorldRegistrations,
    resourceWorld: defaultResourceWorldRegistrations,
    conversationPorts: conversationPortRegistrations,
  };
}
