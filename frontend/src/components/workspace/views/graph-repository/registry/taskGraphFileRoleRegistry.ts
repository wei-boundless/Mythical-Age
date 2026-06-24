import type { GraphFileRoleRegistration, GraphTemplateRecord } from "../templates/graphTemplateTypes";
import { builtInGraphTemplates } from "../templates/builtInGraphTemplates";

const defaultFileRoles: GraphFileRoleRegistration[] = [
  {
    role: "source_snapshot",
    displayName: "源资料",
    category: "source",
    pathPattern: "source/",
    contentKind: "text",
    editable: true,
  },
  {
    role: "runtime_evidence",
    displayName: "运行证据",
    category: "runtime",
    pathPattern: "evidence/{node_id}.json",
    contentKind: "json",
    editable: false,
  },
  {
    role: "artifact",
    displayName: "通用产物",
    category: "artifact",
    pathPattern: "artifacts/",
    contentKind: "text",
    editable: false,
  },
];

export function graphFileRolesForTemplate(template: GraphTemplateRecord | null | undefined): GraphFileRoleRegistration[] {
  return [
    ...defaultFileRoles,
    ...(template?.file_space_template?.file_roles ?? []),
  ];
}

export function allGraphFileRoles() {
  const roles = new Map<string, GraphFileRoleRegistration>();
  for (const role of defaultFileRoles) roles.set(role.role, role);
  for (const template of builtInGraphTemplates) {
    for (const role of template.file_space_template?.file_roles ?? []) {
      roles.set(role.role, role);
    }
  }
  return Array.from(roles.values());
}
