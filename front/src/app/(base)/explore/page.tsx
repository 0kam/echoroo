"use client";

import dynamic from "next/dynamic";
import Spinner from "@/lib/components/ui/Spinner";

// Dynamic import to avoid SSR issues with map components
const ExploreLayout = dynamic(
  () => import("@/lib/components/explore/ExploreLayout"),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center min-h-screen">
        <Spinner />
      </div>
    ),
  },
);

export default function ExplorePage() {
  return <ExploreLayout />;
}
