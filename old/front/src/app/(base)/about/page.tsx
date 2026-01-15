"use client";

import { EchorooIcon } from "@/lib/components/icons";
import Hero from "@/lib/components/ui/Hero";

export default function Page() {
  return (
    <div>
      <Hero text="About Echoroo" />
      <div className="p-6 flex flex-col items-center gap-4">
        <div className="flex flex-col items-center p-4">
          <EchorooIcon width={128} height={128} />
          <h1 className="font-sans font-bold text-emerald-500 underline decoration-8 text-6xl">
            Echoroo
          </h1>
          <p className="mt-6 text-2xl leading-8 text-stone-700 dark:text-stone-300">
            Welcome to Echoroo, an open-source web application for audio
            annotation and machine learning.
          </p>
        </div>
        <div className="max-w-prose text-center flex flex-col gap-8 text-lg">
          <p>
            Inspired by the way echolocation sweeps through soundscapes, Echoroo
            helps teams race through large collections of acoustic data while
            keeping every annotation grounded and reliable.
          </p>
          <p>
            At Echoroo, we believe that effective annotation is at the heart of
            a successful machine learning process. Our platform not only
            facilitates audio annotation but also offers robust project
            management capabilities, integrating annotation projects into
            machine learning pipelines.
          </p>
          <p>
            Echoroo is the result of collaborative efforts, developed with the
            support and collaboration of University College London and the
            Mexican National Council for the Humanities, Science, and Technology
            (CONAHCYT). We are committed to providing a powerful and
            user-friendly tool to enhance your audio annotation and machine
            learning endeavors.
          </p>
        </div>
      </div>
    </div>
  );
}
