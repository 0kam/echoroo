import { z } from "zod";
import { SimpleUserSchema } from "./users";

const optionalTrimmedString = z
  .string()
  .optional()
  .transform((value) => {
    if (value === undefined) {
      return undefined;
    }
    const trimmed = value.trim();
    return trimmed === "" ? undefined : trimmed;
  });

const optionalUrl = z
  .string()
  .optional()
  .transform((value) => {
    if (value === undefined) {
      return undefined;
    }
    const trimmed = value.trim();
    return trimmed === "" ? undefined : trimmed;
  });

const optionalEmail = z
  .string()
  .optional()
  .transform((value, ctx) => {
    if (value === undefined) {
      return undefined;
    }
    const trimmed = value.trim();
    if (trimmed === "") {
      return undefined;
    }
    const result = z.string().email().safeParse(trimmed);
    if (!result.success) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Invalid email address",
      });
      return z.NEVER;
    }
    return trimmed;
  });

export const ProjectMemberRoleSchema = z.enum(["manager", "member"]);

export const RecorderSchema = z.object({
  recorder_id: z.string(),
  recorder_name: z.string(),
  manufacturer: z.string().nullable().optional(),
  version: z.string().nullable().optional(),
  usage_count: z.number().int().default(0),
  created_on: z.coerce.date(),
});

export const RecorderCreateSchema = z.object({
  recorder_id: z.string().min(1),
  recorder_name: z.string().min(1),
  manufacturer: optionalTrimmedString,
  version: optionalTrimmedString,
});

export const RecorderUpdateSchema = z.object({
  recorder_name: optionalTrimmedString,
  manufacturer: optionalTrimmedString,
  version: optionalTrimmedString,
});

export const LicenseSchema = z.object({
  license_id: z.string(),
  license_name: z.string(),
  license_link: z.string().url(),
  usage_count: z.number().int().default(0),
  created_on: z.coerce.date(),
});

export const LicenseCreateSchema = z.object({
  license_id: z.string().min(1),
  license_name: z.string().min(1),
  license_link: z.string().trim().url(),
});

export const LicenseUpdateSchema = z.object({
  license_name: optionalTrimmedString,
  license_link: optionalUrl,
});

export const SiteImageSchema = z.object({
  site_image_id: z.string(),
  site_id: z.string(),
  site_image_path: z.string(),
  created_on: z.coerce.date(),
});

export const SiteImageCreateSchema = z.object({
  site_image_id: z.string().min(1),
  site_id: z.string().min(1),
  site_image_path: z.string().min(1),
});

export const SiteImageUpdateSchema = z.object({
  site_image_path: optionalTrimmedString,
});

export const SiteSchema = z.object({
  site_id: z.string(),
  site_name: z.string(),
  project_id: z.string(),
  h3_index: z.string(),
  images: z.array(SiteImageSchema).default([]),
  center_lat: z.number().nullable().optional(),
  center_lon: z.number().nullable().optional(),
  created_on: z.coerce.date(),
});

export const SiteCreateSchema = z.object({
  site_id: z.string().min(1),
  site_name: z.string().min(1),
  project_id: z.string().min(1),
  h3_index: z.string().min(1),
  images: z.array(SiteImageCreateSchema).default([]),
});

export const SiteUpdateSchema = z.object({
  site_name: optionalTrimmedString,
  project_id: optionalTrimmedString,
  h3_index: optionalTrimmedString,
});

export const ProjectMemberSchema = z.object({
  id: z.number().int(),
  project_id: z.string(),
  user_id: z.string().uuid(),
  role: ProjectMemberRoleSchema,
  created_on: z.coerce.date(),
  user: SimpleUserSchema,
});

export const ProjectMemberCreateSchema = z.object({
  user_id: z.string().uuid(),
  role: ProjectMemberRoleSchema.default("member"),
});

export const ProjectMemberUpdateSchema = z.object({
  role: ProjectMemberRoleSchema,
});

export const ProjectSchema = z.object({
  project_id: z.string(),
  project_name: z.string(),
  url: z.string().url().nullable().optional(),
  description: z.string().nullable().optional(),
  target_taxa: z.string().nullable().optional(),
  admin_name: z.string().nullable().optional(),
  admin_email: z.string().email().nullable().optional(),
  is_active: z.boolean(),
  memberships: z.array(ProjectMemberSchema).default([]),
  created_on: z.coerce.date(),
});

export const ProjectCreateSchema = z.object({
  project_name: z.string().min(1),
  url: optionalUrl,
  description: optionalTrimmedString,
  target_taxa: optionalTrimmedString,
  admin_name: optionalTrimmedString,
  admin_email: optionalEmail,
  is_active: z.boolean().default(true),
  initial_members: z.array(ProjectMemberCreateSchema).min(1, {
    message: "At least one project manager must be assigned.",
  }),
});

export const ProjectUpdateSchema = z.object({
  project_name: optionalTrimmedString,
  url: optionalUrl,
  description: optionalTrimmedString,
  target_taxa: optionalTrimmedString,
  admin_name: optionalTrimmedString,
  admin_email: optionalEmail,
  is_active: z.boolean().optional(),
  memberships: z.array(ProjectMemberUpdateSchema).optional(),
});
