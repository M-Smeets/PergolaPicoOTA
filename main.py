# UPDATE THIS BLOCK INSIDE YOUR async def motion():
if s1.get_pos() != pos and not endswitch1():
    s1.en_pin(0)
    await client.publish(PUBLISH_TOPIC1, f"Moving from: " + str(s1.get_pos()) + " to "+ str(pos), qos=1)
    
    # Set the target position ONCE instead of hammering it inside a loop
    s1.target(pos)
    
    # Wait asynchronously until the motor reaches the target position
    while s1.get_pos() != pos and not endswitch1():
        # This line yields CPU control back to the web server and MQTT loops every millisecond
        await asyncio.sleep_ms(1)
        
    updatepos = True
