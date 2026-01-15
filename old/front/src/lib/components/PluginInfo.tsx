import Image from "next/image";
import React from "react";

import Link from "@/lib/components/ui/Link";

export default function PluginInfo({
  name,
  description,
  attribution,
  version,
  thumbnail,
  url,
}: {
  name: string;
  description: string;
  url: string;
  attribution?: string;
  version?: string;
  thumbnail?: string;
}) {
  return (
    <div className="flex flex-col items-center bg-white rounded-lg border shadow md:flex-row md:max-w-xl border-stone-200 dark:bg-stone-800 dark:border-stone-700">
      {thumbnail ? (
        <div className="relative w-full pl-4 md:w-48 md:pl-0 md:pr-4 md:self-stretch">
          <div className="relative h-48 w-full md:h-full">
            <Image
              src={thumbnail}
              alt="Plugin thumbnail"
              fill
              sizes="(min-width: 768px) 12rem, 24rem"
              className="object-cover rounded-md md:rounded-none"
              priority={false}
            />
          </div>
        </div>
      ) : null}
      <div className="flex flex-col justify-between p-4 leading-normal">
        <h5 className="mb-1 text-xl font-bold tracking-tight dark:text-white text-stone-900">
          {name}
        </h5>
        <small className="mb-3 text-sm text-stone-500">
          {version} - {attribution}
        </small>
        <p className="mb-2 text-stone-700 dark:text-stone-400">{description}</p>
        <div className="flex justify-center p-0">
          <Link mode="text" href={url}>
            View
          </Link>
        </div>
      </div>
    </div>
  );
}
