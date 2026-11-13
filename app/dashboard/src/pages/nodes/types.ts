import { NodeType } from "contexts/NodesContext";

export type ServiceNode = NodeType & { id: number; inbound_tags: string[] };
export type ConnectionRecord = {
  id: string;
  timestamp: string;
  user: string;
  identity: string;
  source: string;
  source_ip: string | null;
  source_family: string | null;
  target: string;
  network: string;
  inbound: string;
  outbound: string;
  local: string;
  remote: string;
  remote_ip: string | null;
  egress_family: string | null;
  evidence: "socket" | "access_log";
  status: "opened" | "requested";
};
export type ConnectionSnapshot = {
  type: "snapshot";
  observer: boolean;
  limit: number;
  records: ConnectionRecord[];
};
