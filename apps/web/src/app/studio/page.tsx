import { auth } from "@/lib/auth";
import { redirect } from "next/navigation";
import { StudioClient } from "@/components/studio-client";

export default async function StudioPage() {
  const session = await auth();
  if (!session) redirect("/api/auth/signin");
  return <StudioClient />;
}
