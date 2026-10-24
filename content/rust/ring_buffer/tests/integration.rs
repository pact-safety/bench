use ring_buffer::RingBuffer;

#[test]
fn fills_within_capacity() {
    let mut rb: RingBuffer<i32> = RingBuffer::with_capacity(3);
    rb.push(1);
    rb.push(2);
    assert_eq!(rb.len(), 2);
    assert_eq!(rb.capacity(), 3);
    assert_eq!(rb.to_vec(), vec![1, 2]);
}

#[test]
fn overwrites_oldest_when_full() {
    let mut rb: RingBuffer<i32> = RingBuffer::with_capacity(3);
    rb.push(1);
    rb.push(2);
    rb.push(3);
    rb.push(4);
    assert_eq!(rb.len(), 3);
    assert_eq!(rb.to_vec(), vec![2, 3, 4]);
    rb.push(5);
    assert_eq!(rb.to_vec(), vec![3, 4, 5]);
}

#[test]
fn capacity_zero_accepts_no_pushes() {
    let mut rb: RingBuffer<i32> = RingBuffer::with_capacity(0);
    rb.push(1);
    assert_eq!(rb.len(), 0);
    assert_eq!(rb.to_vec(), Vec::<i32>::new());
}

#[test]
fn capacity_one_keeps_only_latest() {
    let mut rb: RingBuffer<i32> = RingBuffer::with_capacity(1);
    rb.push(10);
    rb.push(20);
    rb.push(30);
    assert_eq!(rb.to_vec(), vec![30]);
}
