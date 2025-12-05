"use client";

import { useRouter, useParams, notFound } from "next/navigation";
import { type ReactNode } from "react";
import { toast } from "react-hot-toast";

import ProjectHeader from "@/app/components/annotation_projects/AnnotationProjectHeader";

import useAnnotationProject from "@/app/hooks/api/useAnnotationProject";

import Loading from "@/app/loading";

import AnnotationProjectContext from "../../../contexts/annotationProject";

export default function Layout({ children }: { children: ReactNode }) {
  const params = useParams();
  const router = useRouter();

  const uuid = params.annotation_project_uuid as string;

  if (!uuid) {
    notFound();
  }

  // Fetch the annotation project.
  const project = useAnnotationProject({
    uuid: uuid,
  });

  if (project.isLoading) {
    return <Loading />;
  }

  if (project.isError || project.data == null) {
    toast.error("Annotation project not found.");
    router.push("/annotation_projects/");
    return null;
  }

  return (
    <AnnotationProjectContext.Provider value={project.data}>
      <ProjectHeader annotationProject={project.data} />
      <div className="p-4">{children}</div>
    </AnnotationProjectContext.Provider>
  );
}
