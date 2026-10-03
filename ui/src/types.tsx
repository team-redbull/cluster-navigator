import { Boxes, LayoutGrid, MousePointerClick, Server } from "lucide-react";
import type { ComponentType } from "react";
import type { ClusterType } from "./api";
import { KubeVirtLogo } from "./components/parts";

/** Anything that can stand as a menu icon: a line icon, or a product's own logo. */
export type TypeIcon = ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

/** One icon per cluster type, used in the menu and anywhere the type is shown. */
export const TYPE_ICONS: Record<ClusterType, TypeIcon> = {
  generic: Server,
  click: MousePointerClick,
  mce: Boxes,
  kubevirt: KubeVirtLogo,
};

/** The view that lists every cluster the user may see, whatever its type. */
export const ALL = "all";
export const ALL_LABEL = "All clusters";
export const ALL_ICON: TypeIcon = LayoutGrid;
