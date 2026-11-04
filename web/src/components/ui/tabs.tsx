import * as T from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

export const Tabs = T.Root;
export const TabsList = ({ className, ...props }: T.TabsListProps) => (
  <T.List className={cn("flex gap-1 overflow-x-auto border-b", className)} {...props} />
);
export const TabsTrigger = ({ className, ...props }: T.TabsTriggerProps) => (
  <T.Trigger
    className={cn(
      "border-b-2 border-transparent px-4 py-2.5 text-sm font-medium whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground data-[state=active]:border-primary data-[state=active]:text-foreground",
      className,
    )}
    {...props}
  />
);
export const TabsContent = ({ className, ...props }: T.TabsContentProps) => (
  <T.Content className={cn("pt-5", className)} {...props} />
);
