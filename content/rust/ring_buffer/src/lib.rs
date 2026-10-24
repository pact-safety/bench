pub struct RingBuffer<T> {
    buf: Vec<Option<T>>,
    head: usize,
    len: usize,
}

impl<T: Clone> RingBuffer<T> {
    pub fn with_capacity(_cap: usize) -> Self { unimplemented!() }
    pub fn push(&mut self, _item: T) { unimplemented!() }
    pub fn len(&self) -> usize { unimplemented!() }
    pub fn capacity(&self) -> usize { unimplemented!() }
    pub fn to_vec(&self) -> Vec<T> { unimplemented!() }
}
