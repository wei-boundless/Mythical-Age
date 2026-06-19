import { TrendDashboard } from "@/components/TrendDashboard";
import { buildSeedSnapshot } from "@/lib/trends";

export default function Page() {
  return <TrendDashboard initialSnapshot={buildSeedSnapshot("all")} />;
}
