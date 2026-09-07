"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TabsContent } from "@/components/ui/tabs";
import { LogsPanel } from "@/components/instances/LogsPanel";
import { EventsPanel } from "@/components/instances/EventsPanel";
import { InstanceEvent, LogsQuery, PodLogs } from "@/types/models";

/**
 * The "logs" and "events" `TabsContent` panes shared by the three instance
 * detail pages (inference, notebook, vector database). Mount this inside a
 * `Tabs` whose own `TabsList` already has triggers for "logs" and "events";
 * this component renders no list or triggers of its own, since the three
 * pages differ there (tab count, controlled vs. uncontrolled value).
 */
export function InspectionTabs({
  fetchLogs,
  fetchEvents,
}: {
  fetchLogs: (query: LogsQuery) => Promise<PodLogs>;
  fetchEvents: () => Promise<InstanceEvent[]>;
}) {
  return (
    <>
      <TabsContent value="logs">
        <Card>
          <CardHeader>
            <CardTitle>Logs</CardTitle>
          </CardHeader>
          <CardContent>
            <LogsPanel fetchLogs={fetchLogs} />
          </CardContent>
        </Card>
      </TabsContent>
      <TabsContent value="events">
        <Card>
          <CardHeader>
            <CardTitle>Events</CardTitle>
          </CardHeader>
          <CardContent>
            <EventsPanel fetchEvents={fetchEvents} />
          </CardContent>
        </Card>
      </TabsContent>
    </>
  );
}
