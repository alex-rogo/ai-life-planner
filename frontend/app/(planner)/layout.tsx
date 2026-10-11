import { Suspense } from "react";
import Planner from "../../components/planner";

// The planner lives in this shared layout so it stays mounted while Day, Week and Month routes change.
export default function PlannerLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <><Suspense><Planner /></Suspense>{children}</>;
}
