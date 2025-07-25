.global flashio_worker_begin
.global flashio_worker_end

.balign 4

flashio_worker_begin:
# a0 ... flash base address
# a1 ... data pointer
# a2 ... data length
# a3 ... optional WREN cmd (0 = disable)

mv t3, ra

# address of SPI ctrl reg
li   a0, 0xb0000000
# enter bypass mode
lbu   t1, 0(a0)
ori   t1, t1, 0x1
sb    t1, 0(a0)
call flashio_wait_bypass_ready

beqz a3, flashio_xfer

sb a3, 8(a0) # send wren
call flashio_wait_bypass_ready
li t1, 2 # deselect
sb t1, 4(a0)
call flashio_wait_bypass_ready

flashio_xfer:
beqz a2, flashio_done
lbu t1, 0(a1)
sb t1, 8(a0) # tx data
call flashio_wait_bypass_ready
lbu t1, 12(a0) # rx data
sb t1, 0(a1)
addi a1, a1, 1
addi a2, a2, -1
j flashio_xfer

flashio_done:
# exit bypass mode
lbu   t1, 0(a0)
andi   t1, t1, 0xFE
sb    t1, 0(a0)

fence.i
mv ra, t3
ret

flashio_wait_bypass_ready:
lbu   t1, 4(a0)
andi t1, t1, 0x1
beqz t1, flashio_wait_bypass_ready
ret

.balign 4
flashio_worker_end:
