import { z } from "zod";

import * as schemas from "@/lib/schemas";

export type GroupRole = z.infer<typeof schemas.GroupRoleSchema>;

export type Group = z.infer<typeof schemas.GroupSchema>;

export type GroupDetail = z.infer<typeof schemas.GroupDetailSchema>;

export type GroupCreate = z.input<typeof schemas.GroupCreateSchema>;

export type GroupUpdate = z.input<typeof schemas.GroupUpdateSchema>;

export type GroupMembership = z.infer<typeof schemas.GroupMembershipSchema>;

export type GroupMembershipCreate = z.input<
  typeof schemas.GroupMembershipCreateSchema
>;

export type GroupMembershipUpdate = z.input<
  typeof schemas.GroupMembershipUpdateSchema
>;
