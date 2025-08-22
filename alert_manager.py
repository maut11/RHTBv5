# alert_manager.py - Resilient Alert System with Auto-Recovery
import asyncio
import aiohttp
import json
import time
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from config import *

class AlertCircuitBreaker:
    """Circuit breaker pattern for alert failures"""
    
    def __init__(self):
        self.failure_count = 0
        self.last_failure_time = 0
        self.failure_threshold = 5
        self.recovery_timeout = 300  # 5 minutes
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        
    async def call_with_circuit_breaker(self, alert_func, *args):
        """Execute alert with circuit breaker protection"""
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
                print("🔄 Circuit breaker moving to HALF_OPEN state")
            else:
                print("⚡ Circuit breaker OPEN - using fallback")
                await self.fallback_alert(*args)
                return False
                
        try:
            result = await alert_func(*args)
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
                print("✅ Circuit breaker CLOSED - normal operation restored")
            return result
            
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                print(f"🚨 Circuit breaker OPEN after {self.failure_count} failures")
            
            await self.fallback_alert(*args)
            return False
    
    async def fallback_alert(self, webhook_url, payload, alert_type):
        """Fallback alert method"""
        try:
            # Log to file as backup
            timestamp = datetime.now(timezone.utc).isoformat()
            with open("emergency_alerts.log", "a") as f:
                f.write(f"{timestamp} | {alert_type} | {json.dumps(payload)}\n")
            print(f"📝 Alert logged to emergency file: {alert_type}")
        except:
            print(f"🚨🚨🚨 CRITICAL: Could not save emergency alert: {alert_type}")

class PersistentAlertQueue:
    """Queue with disk persistence for critical alerts"""
    
    def __init__(self):
        self.memory_queue = asyncio.Queue()
        self.backup_file = "alert_queue_backup.json"
        self.lock = asyncio.Lock()
        
    async def put(self, alert_data):
        """Add alert with optional disk backup"""
        await self.memory_queue.put(alert_data)
        
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
            'circuit_breaker_trips': 0
        }
        
    def record_success(self):
        """Record successful alert"""
        self.metrics['total_alerts_sent'] += 1
        self.metrics['successful_alerts'] += 1
        self.metrics['last_successful_alert'] = time.time()
        
    def record_failure(self):
        """Record failed alert"""
        self.metrics['total_alerts_sent'] += 1
        self.metrics['failed_alerts'] += 1
        
    def record_restart(self):
        """Record processor restart"""
        self.metrics['processor_restarts'] += 1
        
    def get_health_status(self):
        """Get comprehensive health status"""
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
            'restarts': self.metrics['processor_restarts']
        }

class ResilientAlertManager:
    """Main alert manager with resilience features"""
    
    def __init__(self):
        self.queue = PersistentAlertQueue()
        self.circuit_breaker = AlertCircuitBreaker()
        self.health_monitor = AlertHealthMonitor()
        
        # Processor management
        self.primary_processor = None
        self.backup_processor = None
        self.watchdog_task = None
        self.is_running = False
        
        # Configuration
        self.min_delay = 0.5
        self.max_retries = 3
        self.watchdog_interval = 30  # Check every 30 seconds
        
        print("✅ Resilient Alert Manager initialized")
    
    async def start(self):
        """Start the alert system with all components"""
        if self.is_running:
            return
            
        self.is_running = True
        
        # Restore any backed up alerts
        await self.queue.restore_from_backup()
        
        # Start processors
        await self._start_processors()
        
        # Start watchdog
        self.watchdog_task = asyncio.create_task(self._watchdog_monitor())
        
        print("✅ Alert system started with dual processors and watchdog")
    
    async def stop(self):
        """Clean shutdown of alert system"""
        self.is_running = False
        
        # Cancel tasks
        if self.primary_processor:
            self.primary_processor.cancel()
        if self.backup_processor:
            self.backup_processor.cancel()
        if self.watchdog_task:
            self.watchdog_task.cancel()
            
        # Wait for graceful shutdown
        await asyncio.sleep(1)
        print("✅ Alert system stopped")
    
    async def _start_processors(self):
        """Start primary and backup processors"""
        self.primary_processor = asyncio.create_task(self._process_alerts("PRIMARY"))
        await asyncio.sleep(2)  # Stagger startup
        self.backup_processor = asyncio.create_task(self._process_alerts("BACKUP"))
        
    async def _process_alerts(self, processor_name):
        """Alert processor with automatic restart capability"""
        consecutive_failures = 0
        
        while self.is_running:
            try:
                # Get next alert from queue
                try:
                    alert_item = await asyncio.wait_for(self.queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue
                
                # Process the alert
                success = await self._send_alert_with_retry(alert_item, processor_name)
                
                if success:
                    self.health_monitor.record_success()
                    consecutive_failures = 0
                else:
                    self.health_monitor.record_failure()
                    consecutive_failures += 1
                
                # Back off on repeated failures
                if consecutive_failures >= 3:
                    print(f"⚠️ {processor_name} backing off after {consecutive_failures} failures")
                    await asyncio.sleep(30)
                    consecutive_failures = 0
                else:
                    await asyncio.sleep(self.min_delay)
                
            except asyncio.CancelledError:
                print(f"🔌 {processor_name} processor cancelled")
                break
            except Exception as e:
                consecutive_failures += 1
                print(f"❌ {processor_name} processor error: {e}")
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
        
        success = await self.circuit_breaker.call_with_circuit_breaker(
            send_alert, webhook_url, payload, alert_type
        )
        
        if success:
            print(f"✅ [{processor_name}] Alert sent: {alert_id}")
        else:
            print(f"❌ [{processor_name}] Alert failed: {alert_id}")
        
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
                                print(f"✅ Alert {alert_id} succeeded on retry {attempt}")
                            return True
                        else:
                            print(f"⚠️ Alert {alert_id} HTTP {resp.status} on attempt {attempt + 1}")
                            
            except asyncio.TimeoutError:
                print(f"⏰ Alert {alert_id} timeout on attempt {attempt + 1}")
            except Exception as e:
                print(f"❌ Alert {alert_id} error on attempt {attempt + 1}: {e}")
            
            # Exponential backoff between retries
            if attempt < self.max_retries:
                delay = min(2 ** attempt, 10)
                await asyncio.sleep(delay)
        
        return False
    
    async def _watchdog_monitor(self):
        """Watchdog to monitor processor health"""
        while self.is_running:
            try:
                await asyncio.sleep(self.watchdog_interval)
                
                # Check if processors are alive
                primary_alive = self.primary_processor and not self.primary_processor.done()
                backup_alive = self.backup_processor and not self.backup_processor.done()
                
                # Restart dead processors
                if not primary_alive:
                    print("🚨 Primary processor dead - restarting")
                    self.primary_processor = asyncio.create_task(self._process_alerts("PRIMARY"))
                    self.health_monitor.record_restart()
                
                if not backup_alive:
                    print("🚨 Backup processor dead - restarting")
                    self.backup_processor = asyncio.create_task(self._process_alerts("BACKUP"))
                    self.health_monitor.record_restart()
                
                # Check overall health
                health_status = self.health_monitor.get_health_status()
                if health_status['status'] == 'CRITICAL':
                    await self._send_emergency_alert(f"Alert system critical: {health_status['issue']}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"❌ Watchdog error: {e}")
    
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
                        print(f"🚨 Emergency alert sent: {message}")
                        return
        except:
            pass
        
        # Fallback to file logging
        try:
            timestamp = datetime.now(timezone.utc).isoformat()
            with open("emergency_alerts.log", "a") as f:
                f.write(f"{timestamp} | EMERGENCY: {message}\n")
            print(f"📝 Emergency logged to file: {message}")
        except:
            pass
        
        # Last resort - console
        print(f"🚨🚨🚨 EMERGENCY ALERT: {message}")
    
    # Public API methods
    async def add_alert(self, webhook_url: str, payload: Dict, alert_type: str = "general", priority: int = 0):
        """Add alert to queue"""
        alert_item = {
            'id': f"alert_{int(time.time() * 1000)}_{self.health_monitor.metrics['total_alerts_sent']}",
            'webhook_url': webhook_url,
            'payload': payload,
            'alert_type': alert_type,
            'priority': priority,
            'created_at': datetime.now(timezone.utc).isoformat()
        }
        
        await self.queue.put(alert_item)
        
    async def send_error_alert(self, error_message: str, context: Dict = None):
        """Send error alert with context"""
        error_embed = {
            "title": "❌ RHTB Error Alert",
            "description": f"```{error_message}```",
            "color": 0xFF0000,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        if context:
            context_text = []
            for key, value in context.items():
                context_text.append(f"**{key.title()}:** {value}")
            
            error_embed["fields"] = [{
                "name": "ℹ️ Context",
                "value": "\n".join(context_text),
                "inline": False
            }]
        
        await self.add_alert(ALL_NOTIFICATION_WEBHOOK, {"embeds": [error_embed]}, "error_alert", priority=2)
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get comprehensive system metrics"""
        health_status = self.health_monitor.get_health_status()
        
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
        metrics = await self.get_metrics()
        
        return {
            'status': metrics['health_status'],
            'primary_alive': metrics['primary_alive'],
            'backup_alive': metrics['backup_alive'],
            'circuit_state': metrics['circuit_state'],
            'successful_alerts': self.health_monitor.metrics['successful_alerts'],
            'failed_alerts': self.health_monitor.metrics['failed_alerts'],
            'restarts': self.health_monitor.metrics['processor_restarts'],
            'last_alert_age': metrics['last_alert_age']
        }
    
    async def emergency_restart(self):
        """Emergency restart of all processors"""
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
        
        self.health_monitor.record_restart()
        print("✅ Emergency restart completed")