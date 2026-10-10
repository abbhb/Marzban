import { ExternalSubscriptionsWorkspace } from "../commerce/ExternalSubscriptionsWorkspace";
import { usePortalContext } from "./PortalLayout";

export const PortalExternalSubscriptions = () => {
  const { me } = usePortalContext();
  return <ExternalSubscriptionsWorkspace key={me.id} privateAccountId={me.id} />;
};
