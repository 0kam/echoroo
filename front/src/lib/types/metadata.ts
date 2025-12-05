import { z } from "zod";

import * as schemas from "@/lib/schemas";

export type Recorder = z.infer<typeof schemas.RecorderSchema>;
export type RecorderCreate = z.input<typeof schemas.RecorderCreateSchema>;
export type RecorderUpdate = z.input<typeof schemas.RecorderUpdateSchema>;

export type License = z.infer<typeof schemas.LicenseSchema>;
export type LicenseCreate = z.input<typeof schemas.LicenseCreateSchema>;
export type LicenseUpdate = z.input<typeof schemas.LicenseUpdateSchema>;

export type SiteImage = z.infer<typeof schemas.SiteImageSchema>;
export type SiteImageCreate = z.input<typeof schemas.SiteImageCreateSchema>;
export type SiteImageUpdate = z.input<typeof schemas.SiteImageUpdateSchema>;

export type Site = z.infer<typeof schemas.SiteSchema>;
export type SiteCreate = z.input<typeof schemas.SiteCreateSchema>;
export type SiteUpdate = z.input<typeof schemas.SiteUpdateSchema>;

export type Project = z.infer<typeof schemas.ProjectSchema>;
export type ProjectCreate = z.input<typeof schemas.ProjectCreateSchema>;
export type ProjectUpdate = z.input<typeof schemas.ProjectUpdateSchema>;
export type ProjectMemberRole = z.infer<typeof schemas.ProjectMemberRoleSchema>;
export type ProjectMember = z.infer<typeof schemas.ProjectMemberSchema>;
export type ProjectMemberCreate = z.input<
  typeof schemas.ProjectMemberCreateSchema
>;
export type ProjectMemberUpdate = z.input<
  typeof schemas.ProjectMemberUpdateSchema
>;

export type MetadataSearch = {
  search?: string;
  project_id?: string;
};
