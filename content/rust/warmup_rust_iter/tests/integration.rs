use warmup_rust_iter::pos_squares;

#[test]
fn basic() {
    assert_eq!(pos_squares(&[1, -2, 3, 0]), vec![1, 9]);
    assert_eq!(pos_squares(&[]), Vec::<i64>::new());
    assert_eq!(pos_squares(&[-1, -2, -3]), Vec::<i64>::new());
    assert_eq!(pos_squares(&[5, 10]), vec![25, 100]);
}
