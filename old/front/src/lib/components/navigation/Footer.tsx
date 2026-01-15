import { version } from "@/app/version";

function EchorooVersion() {
  return <div className="text-stone-500">Echoroo version: {version}</div>;
}

export function Footer() {
  return (
    <nav className="mt-auto">
      <div className="flex z-50 flex-wrap justify-between items-center p-4">
        <EchorooVersion />
      </div>
    </nav>
  );
}
