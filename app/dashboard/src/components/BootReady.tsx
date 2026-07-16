import { bootStage, completeBoot } from "boot";
import { useEffect } from "react";

export const BootReady = ({ ready = true }: { ready?: boolean }) => {
  useEffect(() => {
    if (!ready) return;
    bootStage("route");
    completeBoot();
  }, [ready]);

  return null;
};
