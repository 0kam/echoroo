"use client";

import Image from "next/image";

import Card from "@/lib/components/ui/Card";
import Link from "@/lib/components/ui/Link";

export default function Page() {
  return (
    <div className="container mx-auto p-16">
      <div className="flex flex-col gap-4">
        <h1 className="text-center text-7xl">
          <span className="text-6xl font-thin">Welcome to</span>
          <br />
          <Image
            src="/echoroo.png"
            alt="Echoroo logo"
            width={100}
            height={100}
            className="m-2 inline"
          />
          <span className="font-sans font-bold text-emerald-500 underline decoration-8">
            Echoroo
          </span>
        </h1>
        <h2 className="text-center text-3xl text-stone-500 dark:text-stone-500">
          Rapid acoustic annotation built for machine learning teams.
        </h2>
      </div>
      <div className="pt-16">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 max-w-5xl mx-auto">
          <Card className="p-6 justify-between">
            <h2 className="text-2xl font-bold mb-4">
              Projects
            </h2>
            <p className="text-sm mb-4">
              Browse and manage research projects. Each project contains datasets, annotation tasks, and team members working together.
            </p>
            <Link
              mode="text"
              href="/projects/"
              className="text-sm underline font-bold"
            >
              View Projects
            </Link>
          </Card>
          <Card className="p-6 justify-between">
            <h2 className="text-2xl font-bold mb-4">Explore</h2>
            <p className="text-sm mb-4">
              Search and explore audio recordings across all datasets. Filter by location, time, species, and more.
            </p>
            <Link
              mode="text"
              href="/explore/"
              className="text-sm underline font-bold"
            >
              Start Exploring
            </Link>
          </Card>
          <Card className="p-6 justify-between">
            <h2 className="text-2xl font-bold mb-4">System Admin</h2>
            <p className="text-sm mb-4">
              Manage users, metadata, and system-wide settings. Access requires administrator privileges.
            </p>
            <Link
              mode="text"
              href="/admin/"
              className="text-sm underline font-bold"
            >
              Admin Panel
            </Link>
          </Card>
        </div>
      </div>
    </div>
  );
}
