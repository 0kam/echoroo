import { z } from "zod";

import { UserSchema } from "./users";

export const GroupRoleSchema = z.enum(["member", "manager"]);

export const GroupSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  description: z.string().nullable().optional(),
  created_on: z.coerce.date(),
  created_by_id: z.string().uuid().nullable().optional(),
});

export const GroupMembershipSchema = z.object({
  group_id: z.number().int(),
  user_id: z.string().uuid(),
  role: GroupRoleSchema,
  created_on: z.coerce.date(),
  user: UserSchema.optional(),
});

export const GroupDetailSchema = GroupSchema.extend({
  memberships: z.array(GroupMembershipSchema).default([]),
});

export const GroupCreateSchema = z.object({
  name: z.string().min(1),
  description: z.string().optional(),
});

export const GroupUpdateSchema = GroupCreateSchema.partial();

export const GroupMembershipCreateSchema = z.object({
  user_id: z.string().uuid(),
  role: GroupRoleSchema.default("member"),
});

export const GroupMembershipUpdateSchema = z.object({
  role: GroupRoleSchema,
});
