"""
Smoke test for CTP error code handling functionality.
This test verifies that the basic error code handling infrastructure is in place.
"""
from vnpy.trader.object import OrderData
from vnpy.trader.constant import Status, Direction, Offset, Exchange
from vnpy.trader.event import EVENT_ORDER
from src.core.engine import TestEngine
from src.core.risk import TestRiskManager


def test_risk_manager_rejection_counter():
    """Verify that TestRiskManager has rejection_count attribute and on_order_rejected method."""
    rm = TestRiskManager()
    
    # Check initial state
    assert hasattr(rm, 'rejection_count'), "TestRiskManager should have rejection_count attribute"
    assert rm.rejection_count == 0, "Initial rejection_count should be 0"
    
    # Check method exists
    assert hasattr(rm, 'on_order_rejected'), "TestRiskManager should have on_order_rejected method"
    
    # Create a mock order
    order = OrderData(
        gateway_name="TEST",
        symbol="rb2505",
        exchange=Exchange.SHFE,
        orderid="1",
        direction=Direction.LONG,
        offset=Offset.OPEN,
        price=4000.0,
        volume=1,
        status=Status.REJECTED,
    )
    order.reject_code = 26
    order.reject_reason = "资金不足"
    
    # Call the method
    rm.on_order_rejected(order)
    
    # Verify counter incremented
    assert rm.rejection_count == 1, "rejection_count should be 1 after one rejection"
    
    # Check get_metrics includes rejection_count
    metrics = rm.get_metrics()
    assert 'rejection_count' in metrics, "get_metrics should include rejection_count"
    assert metrics['rejection_count'] == 1, "metrics rejection_count should be 1"
    
    # Check reset_counters resets rejection_count
    rm.reset_counters()
    assert rm.rejection_count == 0, "rejection_count should be 0 after reset"
    
    print("✓ TestRiskManager rejection tracking works correctly")


def test_engine_rejection_storage():
    """Verify that TestEngine has rejection storage and methods."""
    engine = TestEngine()
    
    # Check attributes exist
    assert hasattr(engine, 'rejected_orders'), "TestEngine should have rejected_orders attribute"
    assert hasattr(engine, '_on_reject_callbacks'), "TestEngine should have _on_reject_callbacks attribute"
    
    # Check methods exist
    assert hasattr(engine, '_process_rejection'), "TestEngine should have _process_rejection method"
    assert hasattr(engine, 'get_rejected_orders'), "TestEngine should have get_rejected_orders method"
    assert hasattr(engine, 'register_reject_callback'), "TestEngine should have register_reject_callback method"
    
    # Check initial state
    assert len(engine.rejected_orders) == 0, "Initial rejected_orders should be empty"
    assert len(engine._on_reject_callbacks) == 0, "Initial callbacks should be empty"
    
    print("✓ TestEngine rejection storage infrastructure exists")


def test_process_rejection_basic():
    """Verify that _process_rejection handles rejected orders correctly."""
    engine = TestEngine()
    
    # Create a rejected order
    order = OrderData(
        gateway_name="TEST",
        symbol="rb2505",
        exchange=Exchange.SHFE,
        orderid="1",
        direction=Direction.LONG,
        offset=Offset.OPEN,
        price=4000.0,
        volume=1,
        status=Status.REJECTED,
    )
    order.vt_orderid = "TEST.1"
    order.reject_code = 26
    order.reject_reason = "资金不足"
    order.status_msg = "CTP:资金不足"
    
    # Track callback invocations
    callback_invoked = []
    def test_callback(payload):
        callback_invoked.append(payload)
    
    engine.register_reject_callback(test_callback)
    
    # Process the rejection
    engine._process_rejection(order)
    
    # Verify storage
    assert order.vt_orderid in engine.rejected_orders, "Order should be stored in rejected_orders"
    assert engine.rejected_orders[order.vt_orderid] == order, "Stored order should match original"
    
    # Verify risk manager was notified
    assert engine.risk_manager.rejection_count == 1, "Risk manager should have rejection_count = 1"
    
    # Verify callback was invoked
    assert len(callback_invoked) == 1, "Callback should have been invoked once"
    payload = callback_invoked[0]
    assert payload['vt_orderid'] == order.vt_orderid
    assert payload['reject_code'] == 26
    assert payload['reject_reason'] == "资金不足"
    
    # Verify get_rejected_orders works
    rejected = engine.get_rejected_orders()
    assert len(rejected) == 1, "Should have 1 rejected order"
    assert rejected[0] == order, "Retrieved order should match original"
    
    print("✓ _process_rejection handles rejected orders correctly")


def test_process_rejection_non_rejected():
    """Verify that _process_rejection ignores non-rejected orders."""
    engine = TestEngine()
    
    # Create a non-rejected order
    order = OrderData(
        gateway_name="TEST",
        symbol="rb2505",
        exchange=Exchange.SHFE,
        orderid="1",
        direction=Direction.LONG,
        offset=Offset.OPEN,
        price=4000.0,
        volume=1,
        status=Status.NOTTRADED,
    )
    order.vt_orderid = "TEST.1"
    
    # Process the order
    engine._process_rejection(order)
    
    # Verify it was NOT stored
    assert order.vt_orderid not in engine.rejected_orders, "Non-rejected order should not be stored"
    assert engine.risk_manager.rejection_count == 0, "Risk manager rejection_count should still be 0"
    
    print("✓ _process_rejection correctly ignores non-rejected orders")


def test_non_rejected_orders_not_stored():
    """
    Test: non-rejected orders (reject_code=None, status!=REJECTED) do not trigger rejection path.
    Requirements: 1.3
    """
    engine = TestEngine()
    
    # Test case 1: Order with no reject_code and status NOTTRADED
    order1 = OrderData(
        gateway_name="TEST",
        symbol="rb2505",
        exchange=Exchange.SHFE,
        orderid="1",
        direction=Direction.LONG,
        offset=Offset.OPEN,
        price=4000.0,
        volume=1,
        status=Status.NOTTRADED,
    )
    order1.vt_orderid = "TEST.1"
    
    engine._process_rejection(order1)
    
    assert order1.vt_orderid not in engine.rejected_orders, "NOTTRADED order should not be stored"
    assert engine.risk_manager.rejection_count == 0, "Rejection count should be 0"
    
    # Test case 2: Order with no reject_code and status ALLTRADED
    order2 = OrderData(
        gateway_name="TEST",
        symbol="rb2505",
        exchange=Exchange.SHFE,
        orderid="2",
        direction=Direction.LONG,
        offset=Offset.OPEN,
        price=4000.0,
        volume=1,
        status=Status.ALLTRADED,
    )
    order2.vt_orderid = "TEST.2"
    
    engine._process_rejection(order2)
    
    assert order2.vt_orderid not in engine.rejected_orders, "ALLTRADED order should not be stored"
    assert engine.risk_manager.rejection_count == 0, "Rejection count should still be 0"
    
    print("✓ Non-rejected orders are correctly ignored")


def test_cancelled_orders_with_status_msg():
    """
    Test: CANCELLED orders with status_msg log diagnostic info.
    Requirements: 1.3
    """
    engine = TestEngine()
    
    # Create a CANCELLED order with status_msg
    order = OrderData(
        gateway_name="TEST",
        symbol="rb2505",
        exchange=Exchange.SHFE,
        orderid="1",
        direction=Direction.LONG,
        offset=Offset.OPEN,
        price=4000.0,
        volume=1,
        status=Status.CANCELLED,
    )
    order.vt_orderid = "TEST.1"
    order.status_msg = "用户主动撤单"
    
    # Process the order - should log diagnostic info but not store as rejection
    engine._process_rejection(order)
    
    # Verify it was NOT stored as a rejection
    assert order.vt_orderid not in engine.rejected_orders, "CANCELLED order without reject_code should not be stored"
    assert engine.risk_manager.rejection_count == 0, "Rejection count should be 0"
    
    print("✓ CANCELLED orders with status_msg are handled correctly")


def test_callback_exception_does_not_interrupt():
    """
    Test: callback that raises exception does not interrupt processing.
    Requirements: 4.3
    """
    engine = TestEngine()
    
    # Register a callback that raises an exception
    def bad_callback(payload):
        raise ValueError("Callback error!")
    
    # Register a good callback to verify processing continues
    good_callback_invoked = []
    def good_callback(payload):
        good_callback_invoked.append(payload)
    
    engine.register_reject_callback(bad_callback)
    engine.register_reject_callback(good_callback)
    
    # Create a rejected order
    order = OrderData(
        gateway_name="TEST",
        symbol="rb2505",
        exchange=Exchange.SHFE,
        orderid="1",
        direction=Direction.LONG,
        offset=Offset.OPEN,
        price=4000.0,
        volume=1,
        status=Status.REJECTED,
    )
    order.vt_orderid = "TEST.1"
    order.reject_code = 26
    order.reject_reason = "资金不足"
    
    # Process the rejection - should not raise exception
    try:
        engine._process_rejection(order)
    except Exception as e:
        assert False, f"_process_rejection should not propagate callback exceptions, but got: {e}"
    
    # Verify the order was still stored despite callback exception
    assert order.vt_orderid in engine.rejected_orders, "Order should be stored even if callback fails"
    assert engine.risk_manager.rejection_count == 1, "Risk manager should be notified"
    
    # Verify the good callback was still invoked
    assert len(good_callback_invoked) == 1, "Good callback should have been invoked"
    
    print("✓ Callback exceptions are handled gracefully")


def test_process_rejection_exception_does_not_propagate():
    """
    Test: _process_rejection exception does not propagate to on_order.
    Requirements: 5.2
    """
    from vnpy.event import Event
    
    engine = TestEngine()
    
    # Create an order that will cause an exception in _process_rejection
    # We'll simulate this by creating an order with a problematic attribute
    order = OrderData(
        gateway_name="TEST",
        symbol="rb2505",
        exchange=Exchange.SHFE,
        orderid="1",
        direction=Direction.LONG,
        offset=Offset.OPEN,
        price=4000.0,
        volume=1,
        status=Status.REJECTED,
    )
    order.vt_orderid = "TEST.1"
    order.reject_code = 26
    
    # Monkey-patch _process_rejection to raise an exception
    original_process_rejection = engine._process_rejection
    def failing_process_rejection(order):
        raise RuntimeError("Simulated processing error!")
    
    engine._process_rejection = failing_process_rejection
    
    # Create an event and call on_order - should not raise exception
    event = Event(type=EVENT_ORDER, data=order)
    
    try:
        engine.on_order(event)
    except Exception as e:
        assert False, f"on_order should not propagate _process_rejection exceptions, but got: {e}"
    
    # Verify the order was still stored in orders dict (normal processing continued)
    assert order.vt_orderid in engine.orders, "Order should be stored in orders dict"
    
    # Restore original method
    engine._process_rejection = original_process_rejection
    
    print("✓ _process_rejection exceptions do not propagate to on_order")


if __name__ == "__main__":
    print("Running smoke tests for CTP error code handling...\n")
    
    try:
        test_risk_manager_rejection_counter()
        test_engine_rejection_storage()
        test_process_rejection_basic()
        test_process_rejection_non_rejected()
        test_non_rejected_orders_not_stored()
        test_cancelled_orders_with_status_msg()
        test_callback_exception_does_not_interrupt()
        test_process_rejection_exception_does_not_propagate()
        
        print("\n✅ All smoke tests passed!")
        print("\nImplemented functionality:")
        print("  ✓ Task 1.1: TestRiskManager rejection tracking")
        print("  ✓ Task 2.1: TestEngine rejection storage and callbacks")
        print("  ✓ Task 2.2: Integration into on_order callback")
        print("  ✓ Task 4.1: Edge cases and exception safety")
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        raise
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        raise
