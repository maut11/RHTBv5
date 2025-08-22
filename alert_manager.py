# alert_manager.py - Fixed Resilient Alert System with Auto-Recovery
import asyncio
import aiohttp
import json
import time
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from config import *

class AlertCircuitBreaker:
    """Circuit breaker pattern for alert failures with enhanced recovery"""
    
    def __init__(self):
        self.failure_count = 0
        self.last_failure_time = 0
        self.failure_threshold = 5
        self.recovery_timeout = 300  # 5 minutes
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.consecutive_successes = 0
        
    async def call_with_circuit_breaker(self, alert_func):
        """Execute alert with circuit breaker protection"""
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                self.consecutive_successes = 0
                print("🔄 Circuit breaker moving to HALF_OPEN state")
            else:
                print("⚡ Circuit breaker OPEN - using fallback")
                await self._fallback_alert("Circuit breaker open")
                return False
                
        try:
            # Call the alert function
            result = await alert_func()
            
            if self.state == "HALF_OPEN":
                self.consecutive_successes += 1
                if self.consecutive_successes >= 3:  # Require 3 successes to close
                    self.state = "CLOSED"
                    self.failure_count = 0
                    print("✅ Circuit breaker CLOSED - normal operation restored")
            elif self.state == "CLOSED":
                # Reset failure count on success
                self.failure_count = max(0, self.failure_count - 1)
                
            return result
            
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                print(f"🚨 Circuit breaker OPEN after {self.failure_count} failures")
            
            await self._fallback_alert(f"Alert failed: {str(e)}")
            return False
    
    async def _fallback_alert(self, message: str):
        """Fallback alert method"""
        try:
            # Log to file as backup
            timestamp = datetime.now(timezone.utc).isoformat()
            with open("emergency_alerts.log", "a") as f:
                f.write(f"{timestamp} | EMERGENCY | {message}\n")
            print(f"📝 Alert logged to emergency file: {message}")
        except:
            print(f"🚨🚨🚨 CRITICAL: Could not save emergency alert: {message}")

class PersistentAlertQueue:
    """Queue with disk persistence for critical alerts"""
    
    def __init__(self):
        self.memory_queue = asyncio.Queue()
        self.backup_file = "alert_queue_backup.json"
        self.lock = asyncio.Lock()
        self.total_added = 0
        
    async def put(self, alert_data):
        """Add alert with optional disk backup"""
        await self.memory_queue.put(alert_data)
        self.total_added += 1
        
        # Backup critical alerts to disk
        if alert_data.get('priority', 0) >= 2:
            await self._backup_to_disk(alert_data)
    
    async def get(self):
        """Get next alert from queue"""
        return await self.memory_queue.get()
    
    def qsize(self):
        """Get current queue size"""
        return self.memory_queue.qsize()
    
    async def _backup_to_disk(self, alert_data):
        """Backup critical alerts to survive restarts"""
        async with self.lock:
            try:
                with open(self.backup_file, "a") as f:
                    f.write(json.dumps(alert_data) + "\n")
            except Exception as e:
                print(f"❌ Failed to backup alert to disk: {e}")
    
    async def restore_from_backup(self):
        """Restore alerts after restart"""
        async with self.lock:
            try:
                if os.path.exists(self.backup_file):
                    with open(self.backup_file, "r") as f:
                        restored_count = 0
                        for line in f:
                            if line.strip():
                                try:
                                    alert_data = json.loads(line.strip())
                                    await self.memory_queue.put(alert_data)
                                    restored_count += 1
                                except:
                                    continue
                    
                    os.remove(self.backup_file)
                    if restored_count > 0:
                        print(f"✅ Restored {restored_count} alerts from backup")
            except Exception as e:
                print(f"❌ Failed to restore alerts from backup: {e}")

class AlertHealthMonitor:
    """Monitors alert system health and provides metrics"""
    
    def __init__(self):
        self.metrics = {
            'session_start': time.time(),
            'total_alerts_sent': 0,
            'successful_alerts': 0,
            'failed_alerts': 0,
            'processor_restarts': 0,
            'last_successful_alert': time.time(),
            'circuit_breaker_trips': 0,
            'queue_high_water_mark': 0
        }
        self.metrics_lock = asyncio.Lock()
        
    async def record_success(self):
        """Record successful alert"""
        async with self.metrics_lock:
            self.metrics['total_alerts_sent'] += 1
            self.metrics['successful_alerts'] += 1
            self.metrics['last_successful_alert'] = time.time()
        
    async def record_failure(self):
        """Record failed alert"""
        async with self.metrics_lock:
            self.metrics['total_alerts_sent'] += 1
            self.metrics['failed_alerts'] += 1
        
    async def record_restart(self):
        """Record processor restart"""
        async with self.metrics_lock:
            self.metrics['processor_restarts'] += 1
            
    async def update_queue_size(self, size: int):
        """Update queue high water mark"""
        async with self.metrics_lock:
            if size > self.metrics['queue_high_water_mark']:
                self.metrics['queue_high_water_mark'] = size
        
    async def get_health_status(self):
        """Get comprehensive health status"""
        async with self.metrics_lock:
            now = time.time()
            last_alert_age = now - self.metrics['last_successful_alert']
            success_rate = (self.metrics['successful_alerts'] / max(1, self.metrics['total_alerts_sent'])) * 100
            
            # Determine health status
            if last_alert_age > 3600:  # No alerts for 1 hour
                status = 'CRITICAL'
                issue = f'No alerts sent in {last_alert_age/60:.0f} minutes'
            elif success_rate < 80:
                status = 'WARNING'
                issue = f'Low success rate: {success_rate:.1f}%'
            elif self.metrics['failed_alerts'] > 10:
                status = 'WARNING'
                issue = f'High failure count: {self.metrics["failed_alerts"]}'
            else:
                status = 'HEALTHY'
                issue = None
                
            return {
                'status': status,
                'issue': issue,
                'success_rate': success_rate,
                'last_alert_age': int(last_alert_age),
                'total_alerts': self.metrics['total_alerts_sent'],
                'successful_alerts': self.metrics['successful_alerts'],
                'failed_alerts': self.metrics['failed_alerts'],
                'restarts': self.metrics['processor_restarts'],
                'queue_high_water_mark': self.metrics['queue_high_water_mark'],
                'session_duration': now - self.metrics['session_start']
            }

class ResilientAlertManager:
    """Main alert manager with resilience features and proper async integration"""
    
    def __init__(self):
        self.queue = PersistentAlertQueue()
        self.circuit_breaker = AlertCircuitBreaker()
        self.health_monitor = AlertHealthMonitor()
        
        # Processor management
        self.primary_processor = None
        self.backup_processor = None
        self.watchdog_task = None
        self.is_running = False
        self._shutdown_event = asyncio.Event()
        
        # Configuration
        self.min_delay = 0.5
        self.max_retries = 3
        self.watchdog_interval = 30  # Check every 30 seconds
        
        # Setup logging
        self.logger = self._setup_logging()
        
        print("✅ Resilient Alert Manager initialized")
    
    def _setup_logging(self):
        """Setup dedicated alert system logging"""
        logger = logging.getLogger('alert_manager')
        logger.setLevel(logging.DEBUG)
        
        # Create logs directory if it doesn't exist
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        if not logger.handlers:
            handler = logging.FileHandler(log_dir / "alert_manager.log")
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    async def start(self):
        """Start the alert system with all components"""
        if self.is_running:
            return
            
        self.is_running = True
        self._shutdown_event.clear()
        
        # Restore any backed up alerts
        await self.queue.restore_from_backup()
        
        # Start processors
        await self._start_processors()
        
        # Start watchdog
        self.watchdog_task = asyncio.create_task(self._watchdog_monitor())
        
        self.logger.info("Alert system started with dual processors and watchdog")
        print("✅ Alert system started with dual processors and watchdog")
    
    async def stop(self):
        """Clean shutdown of alert system"""
        self.is_running = False
        self._shutdown_event.set()
        
        # Cancel tasks
        tasks_to_cancel = []
        if self.primary_processor:
            tasks_to_cancel.append(self.primary_processor)
        if self.backup_processor:
            tasks_to_cancel.append(self.backup_processor)
        if self.watchdog_task:
            tasks_to_cancel.append(self.watchdog_task)
        
        for task in tasks_to_cancel:
            task.cancel()
            
        # Wait for graceful shutdown
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            
        self.logger.info("Alert system stopped")
        print("✅ Alert system stopped")
    
    async def _start_processors(self):
        """Start primary and backup processors"""
        self.primary_processor = asyncio.create_task(self._process_alerts("PRIMARY"))
        await asyncio.sleep(1)  # Stagger startup
        self.backup_processor = asyncio.create_task(self._process_alerts("BACKUP"))
        
    async def _process_alerts(self, processor_name):
        """Alert processor with automatic restart capability"""
        consecutive_failures = 0
        
        self.logger.info(f"{processor_name} processor started")
        
        while self.is_running and not self._shutdown_event.is_set():
            try:
                # Get next alert from queue with timeout
                try:
                    alert_item = await asyncio.wait_for(
                        self.queue.get(), timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Update queue metrics
                await self.health_monitor.update_queue_size(self.queue.qsize())
                
                # Process the alert
                success = await self._send_alert_with_retry(alert_item, processor_name)
                
                if success:
                    await self.health_monitor.record_success()
                    consecutive_failures = 0
                    self.logger.debug(f"{processor_name} alert sent successfully")
                else:
                    await self.health_monitor.record_failure()
                    consecutive_failures += 1
                    self.logger.warning(f"{processor_name} alert failed")
                
                # Back off on repeated failures
                if consecutive_failures >= 3:
                    self.logger.warning(f"{processor_name} backing off after {consecutive_failures} failures")
                    await asyncio.sleep(30)
                    consecutive_failures = 0
                else:
                    await asyncio.sleep(self.min_delay)
                
            except asyncio.CancelledError:
                self.logger.info(f"{processor_name} processor cancelled")
                break
            except Exception as e:
                consecutive_failures += 1
                self.logger.error(f"{processor_name} processor error: {e}")
                await asyncio.sleep(5)
    
    async def _send_alert_with_retry(self, alert_item: Dict, processor_name: str) -> bool:
        """Send alert with retry logic and circuit breaker"""
        webhook_url = alert_item['webhook_url']
        payload = alert_item['payload']
        alert_id = alert_item['id']
        alert_type = alert_item.get('alert_type', 'general')
        
        # Use circuit breaker
        async def send_alert():
            return await self._direct_send_alert(webhook_url, payload, alert_id)
        
        success = await self.circuit_breaker.call_with_circuit_breaker(send_alert)
        
        if success:
            self.logger.debug(f"[{processor_name}] Alert sent: {alert_id}")
        else:
            self.logger.error(f"[{processor_name}] Alert failed: {alert_id}")
        
        return success
    
    async def _direct_send_alert(self, webhook_url: str, payload: Dict, alert_id: str) -> bool:
        """Direct alert sending with proper error handling"""
        for attempt in range(self.max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    if 'username' not in payload:
                        payload['username'] = "RHTB v4 Enhanced"
                    
                    timeout = aiohttp.ClientTimeout(total=30)
                    
                    async with session.post(webhook_url, json=payload, timeout=timeout) as resp:
                        if resp.status in (200, 204):
                            if attempt > 0:
                                self.logger.info(f"Alert {alert_id} succeeded on retry {attempt}")
                            return True
                        else:
                            error_text = await resp.text()
                            self.logger.warning(f"Alert {alert_id} HTTP {resp.status} on attempt {attempt + 1}: {error_text[:200]}")
                            
            except asyncio.TimeoutError:
                self.logger.warning(f"Alert {alert_id} timeout on attempt {attempt + 1}")
            except aiohttp.ClientError as e:
                self.logger.warning(f"Alert {alert_id} client error on attempt {attempt + 1}: {e}")
            except Exception as e:
                self.logger.warning(f"Alert {alert_id} error on attempt {attempt + 1}: {e}")
            
            # Exponential backoff between retries
            if attempt < self.max_retries:
                delay = min(2 ** attempt, 10)
                await asyncio.sleep(delay)
        
        return False
    
    async def _watchdog_monitor(self):
        """Watchdog to monitor processor health"""
        self.logger.info("Watchdog started")
        
        while self.is_running and not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(self.watchdog_interval)
                
                # Check if processors are alive
                primary_alive = self.primary_processor and not self.primary_processor.done()
                backup_alive = self.backup_processor and not self.backup_processor.done()
                
                # Restart dead processors
                if not primary_alive and self.is_running:
                    self.logger.warning("Primary processor dead - restarting")
                    print("🚨 Primary processor dead - restarting")
                    self.primary_processor = asyncio.create_task(self._process_alerts("PRIMARY"))
                    await self.health_monitor.record_restart()
                
                if not backup_alive and self.is_running:
                    self.logger.warning("Backup processor dead - restarting")  
                    print("🚨 Backup processor dead - restarting")
                    self.backup_processor = asyncio.create_task(self._process_alerts("BACKUP"))
                    await self.health_monitor.record_restart()
                
                # Check overall health
                health_status = await self.health_monitor.get_health_status()
                if health_status['status'] == 'CRITICAL':
                    await self._send_emergency_alert(f"Alert system critical: {health_status.get('issue', 'Unknown issue')}")
                
            except asyncio.CancelledError:
                self.logger.info("Watchdog cancelled")
                break
            except Exception as e:
                self.logger.error(f"Watchdog error: {e}")
    
    async def _send_emergency_alert(self, message: str):
        """Send emergency alert through fallback methods"""
        try:
            # Try direct webhook call
            emergency_payload = {
                "content": f"🚨 EMERGENCY: {message}",
                "username": "RHTB Emergency System"
            }
            
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=10)
                async with session.post(ALL_NOTIFICATION_WEBHOOK, json=emergency_payload, timeout=timeout) as resp:
                    if resp.status in (200, 204):
                        self.logger.info(f"Emergency alert sent: {message}")
                        print(f"🚨 Emergency alert sent: {message}")
                        return
        except Exception as e:
            self.logger.error(f"Failed to send emergency alert via webhook: {e}")
        
        # Fallback to file logging
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            with open("emergency_alerts.log", "a") as f:
                f.write(f"{timestamp} | EMERGENCY: {message}\n")
            self.logger.info(f"Emergency logged to file: {message}")
            print(f"📝 Emergency logged to file: {message}")
        except Exception as e:
            self.logger.error(f"Failed to log emergency to file: {e}")
        
        # Last resort - console
        print(f"🚨🚨🚨 EMERGENCY ALERT: {message}")
    
    # Public API methods
    async def add_alert(self, webhook_url: str, payload: Dict, alert_type: str = "general", priority: int = 0):
        """Add alert to queue"""
        alert_item = {
            'id': f"alert_{int(time.time() * 1000)}_{self.queue.total_added}",
            'webhook_url': webhook_url,
            'payload': payload,
            'alert_type': alert_type,
            'priority': priority,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        await self.queue.put(alert_item)
        self.logger.debug(f"Alert added: {alert_type} (Queue: {self.queue.qsize()})")
        
    async def send_error_alert(self, error_message: str, context: Dict = None):
        """Send error alert with context"""
        try:
            error_embed = {
                "title": "❌ RHTB Error Alert",
                "description": f"```{error_message[:1900]}```",  # Limit length for Discord
                "color": 0xFF0000,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "fields": []
            }
            
            if context:
                context_text = []
                for key, value in list(context.items())[:5]:  # Limit to 5 context items
                    context_text.append(f"**{key.title()}:** {str(value)[:100]}")
                
                if context_text:
                    error_embed["fields"].append({
                        "name": "ℹ️ Context",
                        "value": "\n".join(context_text),
                        "inline": False
                    })
            
            await self.add_alert(ALL_NOTIFICATION_WEBHOOK, {"embeds": [error_embed]}, "error_alert", priority=2)
            
        except Exception as e:
            self.logger.error(f"Failed to send error alert: {e}")
            # Fallback to simple text alert
            try:
                await self.add_alert(ALL_NOTIFICATION_WEBHOOK, {
                    "content": f"❌ Error: {error_message[:1900]}"
                }, "error_alert", priority=2)
            except:
                pass  # Give up gracefully
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get comprehensive system metrics"""
        health_status = await self.health_monitor.get_health_status()
        
        return {
            **health_status,
            'queue_size_current': self.queue.qsize(),
            'is_running': self.is_running,
            'primary_alive': self.primary_processor and not self.primary_processor.done(),
            'backup_alive': self.backup_processor and not self.backup_processor.done(),
            'circuit_state': self.circuit_breaker.state,
            'active_processors': sum([
                self.primary_processor and not self.primary_processor.done(),
                self.backup_processor and not self.backup_processor.done()
            ]),
            'health_status': health_status['status']
        }
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get detailed health status"""
        return await self.health_monitor.get_health_status()
    
    async def emergency_restart(self):
        """Emergency restart of all processors"""
        self.logger.warning("Emergency restart initiated")
        print("🚨 Emergency restart initiated")
        
        # Cancel existing processors
        if self.primary_processor:
            self.primary_processor.cancel()
        if self.backup_processor:
            self.backup_processor.cancel()
        
        # Wait a moment
        await asyncio.sleep(2)
        
        # Restart processors
        await self._start_processors()
        
        await self.health_monitor.record_restart()
        self.logger.info("Emergency restart completed")
        print("✅ Emergency restart completed")
        
    async def test_alert(self, test_message: str = "Test alert from RHTB v4"):
        """Send a test alert to verify system functionality"""
        test_embed = {
            "title": "🧪 Alert System Test",
            "description": test_message,
            "color": 0x3498db,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fields": [
                {
                    "name": "Test Details",
                    "value": f"""
**Timestamp:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}
**Queue Size:** {self.queue.qsize()}
**Circuit State:** {self.circuit_breaker.state}
**System Status:** {'Running' if self.is_running else 'Stopped'}
                    """,
                    "inline": False
                }
            ],
            "footer": {"text": "Alert system test"}
        }
        
        await self.add_alert(ALL_NOTIFICATION_WEBHOOK, {"embeds": [test_embed]}, "test_alert", priority=1)
        self.logger.info("Test alert sent")
        print("🧪 Test alert sent")