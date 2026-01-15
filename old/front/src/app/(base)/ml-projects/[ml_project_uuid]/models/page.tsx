"use client";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

export default function ModelsRedirect() {
  const params = useParams();
  const router = useRouter();
  const mlProjectUuid = params.ml_project_uuid as string;

  useEffect(() => {
    router.replace(`/ml-projects/${mlProjectUuid}/training/`);
  }, [router, mlProjectUuid]);

  return null;
}
