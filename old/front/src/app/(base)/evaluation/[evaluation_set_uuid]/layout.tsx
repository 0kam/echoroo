"use client";

import { useRouter, useParams, notFound } from "next/navigation";
import { type ReactNode } from "react";
import { toast } from "react-hot-toast";

import useEvaluationSet from "@/app/hooks/api/useEvaluationSet";

import EvaluationSetTabs from "./components/EvaluationSetTabs";
import Loading from "@/app/loading";

import EvaluationSetContext from "./context";

export default function Layout({ children }: { children: ReactNode }) {
  const params = useParams();
  const router = useRouter();

  const uuid = params.evaluation_set_uuid as string;

  const {
    isLoading,
    isError,
    data: evaluationSet,
  } = useEvaluationSet({
    uuid: uuid,
    enabled: uuid != null,
  });

  if (!uuid) {
    notFound();
  }

  if (isLoading) {
    return <Loading />;
  }

  if (isError || evaluationSet == null) {
    toast.error("Evaluation set not found.");
    router.push("/evaluation/");
    return null;
  }

  return (
    <EvaluationSetContext.Provider value={evaluationSet}>
      <EvaluationSetTabs evaluationSet={evaluationSet} />
      <div className="p-4">{children}</div>
    </EvaluationSetContext.Provider>
  );
}
