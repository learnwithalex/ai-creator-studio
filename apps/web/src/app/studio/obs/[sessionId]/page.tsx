import { ObsViewerClient } from "@/components/obs-viewer-client";

export default async function ObsPage({
  params,
  searchParams
}: {
  params: Promise<{ sessionId: string }>;
  searchParams: Promise<{ token?: string; signalingUrl?: string }>;
}) {
  const { sessionId } = await params;
  const { token, signalingUrl } = await searchParams;
  return <ObsViewerClient sessionId={sessionId} token={token} signalingUrl={signalingUrl} />;
}
