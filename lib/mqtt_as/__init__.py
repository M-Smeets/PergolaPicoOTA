        else:
            asyncio.create_task(self._connect_handler(self))  # User handler.
    # Launched by .connect(). Runs until connectivity fails. Checks for and
    # handles incoming messages.
    async def _handle_msg(self):
        try:
            while self.isconnected():
                async with self.lock:
                    await self.wait_msg()  # Immediate return if no message
                # https://github.com/peterhinch/micropython-mqtt/issues/166
                # A delay > 0 is necessary for webrepl compatibility.
                await asyncio.sleep_ms(5)  # Let other tasks get lock
        except OSError:
            pass
        self._reconnect()  # Broker or WiFi fail.
    # Keep broker alive MQTT spec 3.1.2.10 Keep Alive.
    # Runs until ping failure or no response in keepalive period.
    async def _keep_alive(self):
        while self.isconnected():
            pings_due = ticks_diff(ticks_ms(), self.last_rx) // self._ping_interval
            if pings_due >= 4:
                self.dprint("Reconnect: broker fail.")
                break
            await asyncio.sleep_ms(self._ping_interval)
            try:
                await self._ping()
            except OSError:
                break
        self._reconnect()  # Broker or WiFi fail.
    async def _kill_tasks(self, kill_skt):  # Cancel running tasks
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        await asyncio.sleep_ms(0)  # Ensure cancellation complete
        if kill_skt:  # Close socket
            self._close()
    # DEBUG: show RAM messages.
    async def _memory(self):
        while True:
            await asyncio.sleep(20)
            gc.collect()
            self.dprint("RAM free %d alloc %d", gc.mem_free(), gc.mem_alloc())
    def isconnected(self):
        if self._in_connect:  # Disable low-level check during .connect()
            return True
        if self._isconnected and not self._sta_if.isconnected():  # It's going down.
            self._reconnect()
        return self._isconnected
    def _reconnect(self):  # Schedule a reconnection if not underway.
        if self._isconnected:
            self._isconnected = False
            asyncio.create_task(self._kill_tasks(True))  # Shut down tasks and socket
            if self._events:  # Signal an outage
                self.down.set()
            else:
                asyncio.create_task(self._wifi_handler(False))  # User handler.
    # Await broker connection.
    async def _connection(self):
        while not self._isconnected:
            await asyncio.sleep(1)
    # Scheduled on 1st successful connection. Runs forever maintaining wifi and
    # broker connection. Must handle conditions at edge of WiFi range.
    async def _keep_connected(self):
        while self._has_connected:
            if self.isconnected():  # Pause for 1 second
                await asyncio.sleep(1)
                gc.collect()
            else:  # Link is down, socket is closed, tasks are killed
                try:
                    self._sta_if.disconnect()
                except OSError:
                    self.dprint("Wi-Fi not started, unable to disconnect interface")
                await asyncio.sleep(1)
                try:
                    await self.wifi_connect()
                except OSError:
                    continue
                if not self._has_connected:  # User has issued the terminal .disconnect()
                    self.dprint("Disconnected, exiting _keep_connected")
                    break
                try:
                    await self.connect()
                    # Now has set ._isconnected and scheduled _connect_handler().
                    self.dprint("Reconnect OK!")
                except OSError as e:
                    self.dprint("Error in reconnect. %s", e)
                    # Can get ECONNABORTED or -1. The latter signifies no or bad CONNACK received.
                    self._close()  # Disconnect and try again.
                    self._in_connect = False
                    self._isconnected = False
        self.dprint("Disconnected, exited _keep_connected")
    async def subscribe(self, topic, qos=0, properties=None):
        qos_check(qos)
        while 1:
            await self._connection()
            try:
                return await super().subscribe(topic, qos, properties)
            except OSError:
                pass
            self._reconnect()  # Broker or WiFi fail.
    async def unsubscribe(self, topic, properties=None):
        while 1:
            await self._connection()
            try:
                return await super().unsubscribe(topic, properties)
            except OSError:
                pass
            self._reconnect()  # Broker or WiFi fail.
    async def publish(self, topic, msg, retain=False, qos=0, properties=None):
        qos_check(qos)
        while 1:
            await self._connection()
