"""
5-Phase Latency Instrumentation System
T0: Alert received → T1: Parsed → T2: Validated → T3: Executed → T4: Targets set → T5: Confirmed
"""
import time
import threading
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import json


@dataclass
class LatencyCheckpoint:
    """Single latency measurement checkpoint"""
    phase: str
    timestamp: float
    description: str
    data: Dict = field(default_factory=dict)


@dataclass 
class LatencySession:
    """Complete latency tracking session for a trade"""
    session_id: str
    channel: str
    alert_type: str
    ticker: str
    checkpoints: List[LatencyCheckpoint] = field(default_factory=list)
    start_time: float = field(default_factory=time.perf_counter)
    metadata: Dict = field(default_factory=dict)
    
    def add_checkpoint(self, phase: str, description: str, data: Dict = None):
        """Add a latency checkpoint with minimal overhead"""
        timestamp = time.perf_counter()
        checkpoint = LatencyCheckpoint(
            phase=phase,
            timestamp=timestamp,
            description=description,
            data=data or {}
        )
        self.checkpoints.append(checkpoint)
        return timestamp
    
    def get_phase_latency(self, from_phase: str, to_phase: str) -> Optional[float]:
        """Get latency between two phases in milliseconds"""
        from_checkpoint = next((c for c in self.checkpoints if c.phase == from_phase), None)
        to_checkpoint = next((c for c in self.checkpoints if c.phase == to_phase), None)
        
        if from_checkpoint and to_checkpoint:
            return (to_checkpoint.timestamp - from_checkpoint.timestamp) * 1000
        return None
    
    def get_total_latency(self) -> float:
        """Get total processing latency in milliseconds"""
        if self.checkpoints:
            return (self.checkpoints[-1].timestamp - self.start_time) * 1000
        return 0.0
    
    def get_latency_breakdown(self) -> Dict[str, float]:
        """Get latency breakdown between all phases"""
        breakdown = {}
        if len(self.checkpoints) < 2:
            return breakdown
            
        # Add T0 (start) → T1 latency
        breakdown['parse_latency_ms'] = self.get_phase_latency('T0', 'T1') or 0.0
        breakdown['validate_latency_ms'] = self.get_phase_latency('T1', 'T2') or 0.0
        breakdown['execute_latency_ms'] = self.get_phase_latency('T2', 'T3') or 0.0
        breakdown['setup_latency_ms'] = self.get_phase_latency('T3', 'T4') or 0.0
        breakdown['confirm_latency_ms'] = self.get_phase_latency('T4', 'T5') or 0.0
        breakdown['total_processing_time_ms'] = self.get_total_latency()
        
        return breakdown
    
    def to_dict(self) -> Dict:
        """Convert session to dictionary for logging/CSV export"""
        return {
            'session_id': self.session_id,
            'channel': self.channel,
            'alert_type': self.alert_type,
            'ticker': self.ticker,
            'start_time': datetime.fromtimestamp(self.start_time).isoformat(),
            'checkpoints': [
                {
                    'phase': c.phase,
                    'timestamp': c.timestamp,
                    'description': c.description,
                    'data': c.data
                }
                for c in self.checkpoints
            ],
            'latency_breakdown': self.get_latency_breakdown(),
            'metadata': self.metadata
        }


class LatencyTracker:
    """
    Thread-safe latency tracking system with minimal overhead
    """
    
    def __init__(self):
        self.active_sessions: Dict[str, LatencySession] = {}
        self.completed_sessions: List[LatencySession] = []
        self._lock = threading.RLock()
        self.max_completed_sessions = 1000  # Memory management
        
    def start_session(self, session_id: str, channel: str, alert_type: str, 
                     ticker: str, metadata: Dict = None) -> LatencySession:
        """
        Start a new latency tracking session
        
        Args:
            session_id: Unique identifier for this trade session
            channel: Trading channel name
            alert_type: Type of alert (entry, exit, trim)
            ticker: Stock/option ticker
            metadata: Additional context data
            
        Returns:
            LatencySession: Started session
        """
        with self._lock:
            session = LatencySession(
                session_id=session_id,
                channel=channel,
                alert_type=alert_type,
                ticker=ticker,
                metadata=metadata or {}
            )
            
            # T0: Alert received
            session.add_checkpoint('T0', 'Alert received', {
                'channel': channel,
                'alert_type': alert_type,
                'ticker': ticker
            })
            
            self.active_sessions[session_id] = session
            return session
    
    def checkpoint(self, session_id: str, phase: str, description: str, 
                  data: Dict = None) -> Optional[float]:
        """
        Add a checkpoint to an active session with minimal overhead
        
        Args:
            session_id: Session identifier
            phase: Phase identifier (T1, T2, T3, T4, T5)
            description: Human-readable description
            data: Optional context data
            
        Returns:
            float: Timestamp of checkpoint or None if session not found
        """
        with self._lock:
            session = self.active_sessions.get(session_id)
            if session:
                return session.add_checkpoint(phase, description, data)
            return None
    
    def complete_session(self, session_id: str, final_data: Dict = None) -> Optional[LatencySession]:
        """
        Complete and archive a latency session
        
        Args:
            session_id: Session identifier
            final_data: Final context data
            
        Returns:
            LatencySession: Completed session or None if not found
        """
        with self._lock:
            session = self.active_sessions.pop(session_id, None)
            if session:
                # T5: Confirmed (completion)
                session.add_checkpoint('T5', 'Trade confirmed/completed', final_data or {})
                
                self.completed_sessions.append(session)
                
                # Memory management - keep only recent sessions
                if len(self.completed_sessions) > self.max_completed_sessions:
                    self.completed_sessions.pop(0)
                    
                return session
            return None
    
    def get_session_breakdown(self, session_id: str) -> Optional[Dict[str, float]]:
        """Get latency breakdown for a session"""
        with self._lock:
            # Check active sessions first
            session = self.active_sessions.get(session_id)
            if session:
                return session.get_latency_breakdown()
                
            # Check completed sessions
            for session in reversed(self.completed_sessions):
                if session.session_id == session_id:
                    return session.get_latency_breakdown()
                    
            return None
    
    def get_recent_sessions(self, limit: int = 50) -> List[Dict]:
        """Get recent completed sessions as dictionaries"""
        with self._lock:
            return [session.to_dict() for session in self.completed_sessions[-limit:]]
    
    def get_average_latencies(self, channel: str = None, alert_type: str = None) -> Dict[str, float]:
        """Get average latencies across sessions"""
        with self._lock:
            relevant_sessions = self.completed_sessions
            
            # Filter by channel/alert_type if specified
            if channel:
                relevant_sessions = [s for s in relevant_sessions if s.channel == channel]
            if alert_type:
                relevant_sessions = [s for s in relevant_sessions if s.alert_type == alert_type]
                
            if not relevant_sessions:
                return {}
                
            # Calculate averages
            totals = {
                'parse_latency_ms': 0.0,
                'validate_latency_ms': 0.0, 
                'execute_latency_ms': 0.0,
                'setup_latency_ms': 0.0,
                'confirm_latency_ms': 0.0,
                'total_processing_time_ms': 0.0
            }
            
            count = len(relevant_sessions)
            for session in relevant_sessions:
                breakdown = session.get_latency_breakdown()
                for key in totals:
                    totals[key] += breakdown.get(key, 0.0)
            
            return {key: value / count for key, value in totals.items()}
    
    def export_to_json(self, filename: str, limit: int = None):
        """Export recent sessions to JSON file"""
        with self._lock:
            sessions = self.completed_sessions
            if limit:
                sessions = sessions[-limit:]
                
            data = {
                'export_time': datetime.now().isoformat(),
                'session_count': len(sessions),
                'sessions': [session.to_dict() for session in sessions]
            }
            
            with open(filename, 'w') as f:
                json.dump(data, f, indent=2, default=str)


# Global latency tracker instance
_global_tracker = LatencyTracker()

def get_latency_tracker() -> LatencyTracker:
    """Get the global latency tracker instance"""
    return _global_tracker

def quick_checkpoint(session_id: str, phase: str, description: str, data: Dict = None):
    """Quick checkpoint function with minimal overhead"""
    return _global_tracker.checkpoint(session_id, phase, description, data)


if __name__ == "__main__":
    # Test the latency tracking system
    tracker = get_latency_tracker()
    
    # Start a test session
    session = tracker.start_session("test_001", "Ryan", "entry", "SPX")
    
    # Simulate processing phases
    time.sleep(0.001)  # 1ms
    quick_checkpoint("test_001", "T1", "Parsed alert", {"method": "fast_regex"})
    
    time.sleep(0.002)  # 2ms 
    quick_checkpoint("test_001", "T2", "Validated trade", {"price": 10.50})
    
    time.sleep(0.005)  # 5ms
    quick_checkpoint("test_001", "T3", "Executed order", {"order_id": "12345"})
    
    time.sleep(0.001)  # 1ms
    quick_checkpoint("test_001", "T4", "Targets set", {"stop_loss": 9.00})
    
    # Complete session
    completed = tracker.complete_session("test_001", {"status": "success"})
    
    if completed:
        print("Latency breakdown:")
        for phase, latency in completed.get_latency_breakdown().items():
            print(f"  {phase}: {latency:.2f}ms")
    
    print("\nLatency tracking test complete")
