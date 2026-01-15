"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import Spinner from "@/lib/components/ui/Spinner";

/**
 * This page redirects to the main explore page.
 * The recordings search functionality has been integrated into /explore/
 */
export default function ExploreRecordingsRedirect() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/explore/");
  }, [router]);

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4">
      <Spinner />
      <p className="text-stone-500 dark:text-stone-400">
        Redirecting to Explore...
      </p>
    </div>
  );
}
